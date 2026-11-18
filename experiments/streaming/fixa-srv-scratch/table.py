import re,os,sys
R=sys.argv[1]
def tot(f):
    t=open(os.path.join(R,f)).read()
    return {m.group(1):int(m.group(2)) for m in re.finditer(r'^(\w+)\s+total\s+(\d+)',t,re.M)}
berk={'edge':4304,'small':14840,'bert_qkv':316791}
v1dense={('edge','24'):4908,('edge','48'):4834,('small','24'):18634,('small','48'):18588,('bert_qkv','24'):459492}
rec_push={('small','24','keeper'):17957,('small','48','keeper'):20431,('bert_qkv','24','keeper'):452740,('bert_qkv','48','keeper'):496569,
 ('edge','24','v1'):8310,('edge','48','v1'):9448,('small','24','v1'):29777,('small','48','v1'):34518,('bert_qkv','24','v1'):651640,('bert_qkv','48','v1'):743192}
rec_dense={('small','24'):17900,('small','48'):18288,('bert_qkv','24'):452257,('bert_qkv','48'):452088}
print('| layer | pat | tiler | dense same chip | push sparse | Fix A sparse | Berkeley stock | FixA vs push | FixA vs Berkeley | FixA vs dense | seeds 1-3 | push vs recorded |')
print('|---|---|---|---|---|---|---|---|---|---|---|---|')
for L in ['edge','small','bert_qkv']:
  for p in ['24','48']:
    for tl,suf,pk in [('keeper','keeperfixa','sparse_v3'),('v1','v1fixa','sparse_stream')]:
      s=[tot('nm%s.%s_%s_%s.seed%d.log'%(p,L,p,suf,k)) for k in (1,2,3)]
      same=all(x==s[0] for x in s)
      d=s[0]; fx=d['sparse_fixa']; pu=d[pk]
      if tl=='keeper': dn=d['dense_v3']; dns='%d'%dn
      else:
        dn=v1dense.get((L,p)); dns=('%d (rec.)'%dn) if dn else 'n/r'
      rp=rec_push.get((L,p,tl)); rps=('%+.2f%% vs %d'%(100*(pu-rp)/rp,rp)) if rp else 'no record'
      if tl=='keeper' and (L,p) in rec_dense:
          rd=rec_dense[(L,p)]; rps+='; dense %+.2f%% vs %d'%(100*(dn-rd)/rd,rd)
      print('| %s | %s:%s | %s | %s | %d | %d | %d | %.3fx | %.3fx | %s | %s | %s |'%(L,p[0],p[1],tl,dns,pu,fx,berk[L],pu/fx,berk[L]/fx,('%.3fx'%(dn/fx)) if dn else '-', 'identical' if same else 'DIFFER', rps))
