"""N:M pruning, retraining and Gemmini-style int8 evaluation for BERT on GLUE MRPC.

Library used by run_config.py. Needs the venv ~/venvs/sparsity-acc (see README.md);
this directory is exempt from the repo's stdlib+matplotlib rule (user approval 2026-11-17).
"""

import math
import random

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils import prune

MODEL_NAME = "bert-base-uncased"
TASK = "mrpc"
MAX_LEN = 128

# Same hparams for dense fine-tune and every sparse retrain (NVIDIA recipe: retrain with the dense recipe).
HPARAMS = {
    "lr": 2e-5,
    "batch_size": 32,
    "epochs": 3,
    "weight_decay": 0.01,
    "warmup_ratio": 0.1,
    "max_grad_norm": 1.0,
    "max_len": MAX_LEN,
    "calib_examples": 512,
}


def set_seed(seed):
    random.seed(seed)
    torch.manual_seed(seed)


def pruned_linears(model):
    """Every nn.Linear inside the encoder; embeddings, pooler and classifier are excluded."""
    out = [(n, m) for n, m in model.named_modules()
           if n.startswith("bert.encoder.") and isinstance(m, nn.Linear)]
    if len(out) != 72:
        raise RuntimeError(f"expected 72 encoder Linear layers, found {len(out)}")
    return out


def nm_mask(w, n, m):
    """Keep the n largest |w| in each group of m consecutive weights along `in` (w is [out, in]).

    Ties go to the lower index, matching nm_prune in gemmini_nm.h (greedy pick, strict >).
    """
    out_f, in_f = w.shape
    if in_f % m:
        raise ValueError(f"in_features {in_f} not a multiple of m={m}")
    g = w.detach().abs().reshape(out_f, in_f // m, m)
    # stable descending sort keeps the lower index first among equal magnitudes
    order = torch.sort(g, dim=-1, descending=True, stable=True).indices
    keep = torch.zeros_like(g, dtype=torch.bool)
    keep.scatter_(-1, order[..., :n], True)
    return keep.reshape(out_f, in_f).to(w.dtype)


def nm_check_tensor(w, n, m):
    """Max nonzeros in any group of m along `in`; raises if > n."""
    out_f, in_f = w.shape
    nz = (w.reshape(out_f, in_f // m, m) != 0).sum(-1)
    worst = int(nz.max())
    if worst > n:
        raise AssertionError(f"n:m check: group with {worst} nonzeros > n={n} (m={m})")
    return worst


def apply_nm(model, n, m):
    """Attach fixed N:M masks (custom_from_mask); pruned weights stay zero through training."""
    for _, lin in pruned_linears(model):
        if prune.is_pruned(lin):
            prune.remove(lin, "weight")
        prune.custom_from_mask(lin, "weight", nm_mask(lin.weight, n, m))


def finalize_masks(model):
    for _, lin in pruned_linears(model):
        if prune.is_pruned(lin):
            prune.remove(lin, "weight")


def verify_nm(model, n, m):
    """Check every pruned layer; return (layers checked, kept fraction). Fails loudly."""
    total = kept = 0
    for name, lin in pruned_linears(model):
        try:
            nm_check_tensor(lin.weight, n, m)
        except AssertionError as e:
            raise AssertionError(f"{name}: {e}") from None
        total += lin.weight.numel()
        kept += int((lin.weight != 0).sum())
    return len(pruned_linears(model)), kept / total


# ---------------------------------------------------------------- data

def load_data(tokenizer):
    from datasets import load_dataset
    ds = load_dataset("nyu-mll/glue", TASK)

    def enc(split):
        d = ds[split]
        e = tokenizer(list(d["sentence1"]), list(d["sentence2"]), truncation=True, max_length=MAX_LEN)
        y = [int(v) for v in d["label"]]
        return [(e["input_ids"][i], e["token_type_ids"][i], y[i]) for i in range(len(d))]

    return enc("train"), enc("validation")


def collate(rows, pad_id):
    L = max(len(r[0]) for r in rows)
    ids = torch.full((len(rows), L), pad_id, dtype=torch.long)
    tt = torch.zeros((len(rows), L), dtype=torch.long)
    att = torch.zeros((len(rows), L), dtype=torch.long)
    for i, (a, t, _) in enumerate(rows):
        ids[i, :len(a)] = torch.tensor(a)
        tt[i, :len(t)] = torch.tensor(t)
        att[i, :len(a)] = 1
    y = torch.tensor([r[2] for r in rows], dtype=torch.long)
    return ids, tt, att, y


def batches(data, bs, pad_id, shuffle_gen=None):
    idx = list(range(len(data)))
    if shuffle_gen is not None:
        idx = torch.randperm(len(data), generator=shuffle_gen).tolist()
    for s in range(0, len(idx), bs):
        yield collate([data[i] for i in idx[s:s + bs]], pad_id)


# ---------------------------------------------------------------- train / eval

def train(model, train_data, pad_id, seed, log, max_steps=None):
    """AdamW + linear warmup/decay, the standard BERT GLUE recipe; returns seconds per epoch."""
    import time
    hp = HPARAMS
    no_decay = ("bias", "LayerNorm.weight")
    params = [
        {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)],
         "weight_decay": hp["weight_decay"]},
        {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)],
         "weight_decay": 0.0},
    ]
    opt = torch.optim.AdamW(params, lr=hp["lr"])
    steps_per_epoch = math.ceil(len(train_data) / hp["batch_size"])
    total = steps_per_epoch * hp["epochs"]
    warm = int(hp["warmup_ratio"] * total)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / max(1, warm) if s < warm else max(0.0, (total - s) / max(1, total - warm)))
    gen = torch.Generator().manual_seed(seed)
    model.train()
    step = 0
    epoch_secs = []
    for ep in range(hp["epochs"]):
        t0 = time.time()
        run_loss = 0.0
        for k, (ids, tt, att, y) in enumerate(batches(train_data, hp["batch_size"], pad_id, gen)):
            loss = F.cross_entropy(model(input_ids=ids, token_type_ids=tt, attention_mask=att).logits, y)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), hp["max_grad_norm"])
            opt.step()
            sched.step()
            step += 1
            run_loss += loss.item()
            if step % 20 == 0:
                log(f"train epoch={ep} step={step}/{total} loss={run_loss / (k + 1):.4f} "
                    f"elapsed={time.time() - t0:.1f}s")
            if max_steps is not None and step >= max_steps:
                epoch_secs.append(time.time() - t0)
                log(f"train stopped at max_steps={max_steps} secs={epoch_secs[-1]:.1f}")
                return epoch_secs, step
        epoch_secs.append(time.time() - t0)
        log(f"train epoch={ep} done loss={run_loss / (k + 1):.4f} secs={epoch_secs[-1]:.1f}")
    return epoch_secs, step


@torch.no_grad()
def evaluate(model, data, pad_id):
    model.eval()
    tp = fp = fn = correct = 0
    for ids, tt, att, y in batches(data, 64, pad_id):
        pred = model(input_ids=ids, token_type_ids=tt, attention_mask=att).logits.argmax(-1)
        correct += int((pred == y).sum())
        tp += int(((pred == 1) & (y == 1)).sum())
        fp += int(((pred == 1) & (y == 0)).sum())
        fn += int(((pred == 0) & (y == 1)).sum())
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return {"accuracy": correct / len(data), "f1": f1, "n": len(data)}


# ---------------------------------------------------------------- Gemmini-style int8

class Int8Linear(nn.Module):
    """Symmetric per-tensor int8 weights and inputs, exact int32 accumulate, one float output scale.

    Mirrors Gemmini: int8 x int8 products summed in int32 (exact here via float64, |acc| < 2^31),
    then a single float scale (s_w * s_x) per layer; bias added in float.
    """

    def __init__(self, lin, x_absmax):
        super().__init__()
        w = lin.weight.detach().double()
        self.s_w = float(w.abs().max()) / 127.0
        self.s_x = float(x_absmax) / 127.0
        if self.s_w == 0 or self.s_x == 0:
            raise RuntimeError("int8: zero scale")
        self.w_q = torch.clamp(torch.round(w / self.s_w), -128, 127)  # zeros stay zero
        self.bias = None if lin.bias is None else lin.bias.detach().double()

    def forward(self, x):
        x_q = torch.clamp(torch.round(x.double() / self.s_x), -128, 127)
        acc = x_q @ self.w_q.t()
        if acc.abs().max() >= 2 ** 31:
            raise OverflowError("int8: int32 accumulator overflow")
        y = acc * (self.s_w * self.s_x)
        if self.bias is not None:
            y = y + self.bias
        return y.to(x.dtype)


@torch.no_grad()
def calibrate(model, calib_data, pad_id):
    """Max |input| per pruned Linear over the calibration set (PTQ, max calibration)."""
    amax = {}
    hooks = []
    for name, lin in pruned_linears(model):
        def h(mod, inp, _out, name=name):
            v = float(inp[0].abs().max())
            amax[name] = max(amax.get(name, 0.0), v)
        hooks.append(lin.register_forward_hook(h))
    model.eval()
    for ids, tt, att, _ in batches(calib_data, 64, pad_id):
        model(input_ids=ids, token_type_ids=tt, attention_mask=att)
    for h in hooks:
        h.remove()
    return amax


def quantize_int8(model, amax):
    """Swap every pruned Linear for Int8Linear in place."""
    for name, lin in pruned_linears(model):
        parent_name, child = name.rsplit(".", 1)
        setattr(model.get_submodule(parent_name), child, Int8Linear(lin, amax[name]))


def verify_nm_int8(model, n, m):
    cnt = 0
    for name, mod in model.named_modules():
        if isinstance(mod, Int8Linear):
            try:
                nm_check_tensor(mod.w_q, n, m)
            except AssertionError as e:
                raise AssertionError(f"{name} (int8): {e}") from None
            cnt += 1
    if cnt != 72:
        raise RuntimeError(f"int8: expected 72 Int8Linear, found {cnt}")
    return cnt
