import re,sys
L=re.compile(r"^core\s+\d+: 0x([0-9a-f]+) \(0x([0-9a-f]+)\)")
seg=[];cur={'n':0,'f':{}};k=0
for line in sys.stdin:
    m=L.match(line)
    if not m: continue
    i=int(m.group(2),16)
    if i&0xFFFFF07F==0xC0002073 or i&0xFFFFF07F==0xC0202073:
        seg.append(cur);cur={'n':0,'f':{}};continue
    cur['n']+=1
    if i&0x7f==0x7b and i&3==3:
        f=i>>25;cur['f'][f]=cur['f'].get(f,0)+1
    if len(seg)>=int(sys.argv[1]): break
for j,s in enumerate(seg): 
    if s['n']<200000: print(j,s['n'],sorted(s['f'].items()))
