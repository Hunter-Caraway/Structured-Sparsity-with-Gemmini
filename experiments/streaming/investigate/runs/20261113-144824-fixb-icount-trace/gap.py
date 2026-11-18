import re,sys
L=re.compile(r"^core\s+\d+: 0x([0-9a-f]+) \(0x([0-9a-f]+)\)")
want=int(sys.argv[1]);seg=0;n=0;pos=[];bounds=[]
for line in sys.stdin:
    m=L.match(line)
    if not m: continue
    i=int(m.group(2),16)
    if i&0xFFFFF07F in (0xC0002073,0xC0202073):
        seg+=1; 
        if seg>want: break
        continue
    if seg==want:
        if i&0x7f==0x7b and i&3==3:
            pos.append((n,i>>25))
        n+=1
print("total",n)
f9=[p for p,f in pos if f==9]
print("first cmd",pos[0],"first f9",f9[0] if f9 else None)
b=[p for p,f in pos if f==8]
print("LOOP_WS at",b)
print("gaps",[b[i+1]-b[i] for i in range(len(b)-1)])
print("tail after last LOOP_WS",n-b[-1])
print("head before first cmd", pos[0][0])
