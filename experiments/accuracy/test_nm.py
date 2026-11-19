"""Checks nm_mask against a line-by-line port of nm_prune (gemmini_nm.h), incl. ties, plus NEG test of the N:M check."""
import torch
import nm_acc as A


def ref(row, n, m):
    out = list(row)
    for g in range(0, len(row), m):
        keep = [False] * m
        for _ in range(n):
            best, bm = -1, -1
            for r in range(m):
                if not keep[r] and abs(row[g + r]) > bm:
                    bm, best = abs(row[g + r]), r
            keep[best] = True
        for r in range(m):
            if not keep[r]:
                out[g + r] = 0
    return out


def main():
    torch.manual_seed(0)
    for n, m in [(2, 4), (4, 8), (8, 16), (1, 4), (2, 8), (4, 16)]:
        w = torch.randint(-3, 4, (64, 96)).float()  # small range forces many ties
        got = w * A.nm_mask(w, n, m)
        exp = torch.tensor([ref(r.tolist(), n, m) for r in w])
        assert torch.equal(got, exp), (n, m)
        A.nm_check_tensor(got, n, m)
        try:
            A.nm_check_tensor(w, n, m)
        except AssertionError:
            pass
        else:
            raise SystemExit(f"NEG: N:M check did not fire for unpruned {n}:{m}")
    print("PASS nm_mask == nm_prune port (6 patterns, with ties); NEG check fires")


if __name__ == "__main__":
    main()
