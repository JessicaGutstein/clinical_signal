"""Builds the synthetic admissions file used by the prototype.

    python scripts/generate_data.py            writes into data/
    python scripts/generate_data.py some/dir   writes somewhere else

The output is fully reproducible (fixed random seed). It writes:

    synthetic_admissions.csv           one row per admission
    planted_hotspots_answer_key.csv    the evaluation set: every pattern planted on
                                       purpose, and what detection should do with it
                                       (scripts/run_evaluation.py scores it)

The evaluation patterns added later (ids H6 onward and D2 onward) are drawn from
their own random stream as extra admissions, so every admission that was in the
file before them is still there, unchanged.

It reads data/icd10_codes.csv (maintained by hand) to give each admission an
ICD-10 diagnosis code inside its diagnosis group. The codes are drawn from their
own random stream, so adding them changed nothing else in the file.

The facilities are real hospitals in and around New York City, with their real
names and locations. Everything else is invented: members, admissions, diagnoses,
dates, amounts, network status, and membership. The planted patterns say nothing
about the real hospitals.

data/facilities.csv (name, type, health system, network status, coordinates) is
maintained by hand and is not produced by this script. data/membership_by_area.csv
is written here.
"""
import csv, math, random, os, sys, datetime as dt
random.seed(7)
_main = random
crng = random.Random(11)  # a separate stream for diagnosis codes, so nothing else shifts
xrng = random.Random(23)  # a separate stream for the later evaluation patterns
xcrng = random.Random(29) # ...and for their diagnosis codes
yrng = random.Random(41)  # a third stream, for the health-system and membership patterns
ycrng = random.Random(43)
code_rng = crng
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(OUT, exist_ok=True)
START, ASOF = dt.date(2024,7,1), dt.date(2026,10,3)
DAILY = 200.0

A,C,P,O,K,E,L,R,T,W = "Acute care","Children's","Psychiatric","Orthopedic specialty","Cancer specialty","Eye and ear specialty","Palliative specialty","Rehabilitation","Long-term acute care","Women's and newborn"
# What each kind of facility is called in the file and on screen.
TYPE_LABEL={A:"Acute care hospital",C:"Children's hospital",P:"Inpatient psychiatric facility",O:"Specialty hospital",K:"Specialty hospital",
 E:"Specialty hospital",L:"Specialty hospital",W:"Specialty hospital",R:"Inpatient rehabilitation facility",T:"Long-term acute care hospital"}
F = []
def add(b, county, rows):
    for n,t,w in rows: F.append(dict(name=n,borough=b,county=county,type=t,w=w))
add("Manhattan","New York",[
("NewYork-Presbyterian/Weill Cornell Medical Center",A,5),("NewYork-Presbyterian/Columbia University Irving Medical Center",A,5),
("NewYork-Presbyterian Allen Hospital",A,1.5),("NewYork-Presbyterian Lower Manhattan Hospital",A,1.5),
("NewYork-Presbyterian Morgan Stanley Children's Hospital",C,1.2),("NewYork-Presbyterian Komansky Children's Hospital",C,0.6),
("NewYork-Presbyterian Alexandra Cohen Hospital for Women and Newborns",W,1.5),("NYU Langone Tisch Hospital",A,5),
("NYU Langone Hassenfeld Children's Hospital",C,0.8),("NYU Langone Orthopedic Hospital",O,0.8),("The Mount Sinai Hospital",A,5),
("Mount Sinai Kravis Children's Hospital",C,0.8),("Mount Sinai Morningside",A,2.5),("Mount Sinai West",A,2.5),
("Mount Sinai Behavioral Health Center",P,0.4),("New York Eye and Ear Infirmary of Mount Sinai",E,0.15),("Lenox Hill Hospital",A,4),
("NYC Health + Hospitals/Bellevue",A,5),("NYC Health + Hospitals/Harlem",A,2),("NYC Health + Hospitals/Metropolitan",A,2),
("NYC Health + Hospitals/Carter",T,0.3),("Memorial Sloan Kettering Cancer Center",K,2),("Hospital for Special Surgery",O,1.8),
("Gracie Square Hospital",P,0.5),("New York State Psychiatric Institute",P,0.15),("Manhattan Psychiatric Center",P,0.15)])
add("Bronx","Bronx",[
("Montefiore Medical Center - Moses Campus",A,5),("Montefiore Medical Center - Weiler Hospital",A,3.5),("Montefiore Medical Center - Wakefield Campus",A,2),
("Children's Hospital at Montefiore",C,1.2),("NYC Health + Hospitals/Jacobi",A,4),("NYC Health + Hospitals/Lincoln",A,4),
("NYC Health + Hospitals/North Central Bronx",A,1.2),("BronxCare Hospital Center - Concourse Division",A,4),
("BronxCare Hospital Center - Fulton Division",P,0.6),("St. Barnabas Hospital",A,2.5),("Calvary Hospital",L,0.4),("Bronx Psychiatric Center",P,0.15)])
add("Brooklyn","Kings",[
("Maimonides Medical Center",A,5),("Maimonides Midwood Community Hospital",A,0.8),("NewYork-Presbyterian Brooklyn Methodist Hospital",A,4.5),
("NYU Langone Hospital - Brooklyn",A,4.5),("The Brooklyn Hospital Center",A,2),("Brookdale University Hospital Medical Center",A,2.5),
("Interfaith Medical Center",A,1.2),("University Hospital at Downstate",A,1.5),("NYC Health + Hospitals/Kings County",A,5),
("NYC Health + Hospitals/Woodhull",A,2),("NYC Health + Hospitals/South Brooklyn Health",A,2.5),("Wyckoff Heights Medical Center",A,2),
("Mount Sinai Brooklyn",A,1),("Kingsboro Psychiatric Center",P,0.15)])
add("Queens","Queens",[
("NewYork-Presbyterian Queens",A,5),("Long Island Jewish Medical Center",A,5),("Cohen Children's Medical Center",C,1.5),
("Zucker Hillside Hospital",P,0.8),("Long Island Jewish Forest Hills",A,2),("Jamaica Hospital Medical Center",A,4.5),
("Flushing Hospital Medical Center",A,2.5),("NYC Health + Hospitals/Elmhurst",A,5),("NYC Health + Hospitals/Queens",A,2.5),
("Mount Sinai Queens",A,2),("St. John's Episcopal Hospital",A,1.5),("Creedmoor Psychiatric Center",P,0.15),("St. Mary's Hospital for Children",C,0.2)])
add("Staten Island","Richmond",[
("Staten Island University Hospital - North",A,4.5),("Staten Island University Hospital - South",A,1.2),
("Richmond University Medical Center",A,2.5),("South Beach Psychiatric Center",P,0.15)])
add("Outside NYC","Nassau",[
("North Shore University Hospital",A,1.5),("NYU Langone Hospital - Long Island",A,1.2),("Mount Sinai South Nassau",A,0.6),
("St. Francis Hospital & Heart Center",A,0.7),("Mercy Hospital",A,0.3),("Nassau University Medical Center",A,0.6),("Glen Cove Hospital",A,0.25),
("Plainview Hospital",A,0.25),("Syosset Hospital",A,0.2),("Long Island Jewish Valley Stream",A,0.6),("St. Joseph Hospital",A,0.2)])
add("Outside NYC","Westchester",[
("Westchester Medical Center",A,0.8),("Maria Fareri Children's Hospital",C,0.2),("White Plains Hospital",A,0.7),("NewYork-Presbyterian Westchester",A,0.5),
("Montefiore New Rochelle Hospital",A,0.5),("Montefiore Mount Vernon Hospital",A,0.4),("St. John's Riverside Hospital",A,0.5),
("St. Joseph's Medical Center",A,0.4),("Phelps Hospital",A,0.3),("Northern Westchester Hospital",A,0.3),
("NewYork-Presbyterian Hudson Valley Hospital",A,0.2),("Burke Rehabilitation Hospital",R,0.2),("Blythedale Children's Hospital",C,0.1),
("NewYork-Presbyterian Westchester Behavioral Health",P,0.3)])
add("Outside NYC","Bergen (NJ)",[("Hackensack University Medical Center",A,0.5),("Englewood Hospital",A,0.3),("Holy Name Medical Center",A,0.3),("The Valley Hospital",A,0.2)])
add("Outside NYC","Hudson (NJ)",[("Jersey City Medical Center",A,0.5),("Palisades Medical Center",A,0.3)])
assert len(F)==100 and len({f["name"] for f in F})==100
# State-run behavioral centers keep patients about three times as long.
LONG_STAY={'Manhattan Psychiatric Center', 'Creedmoor Psychiatric Center', 'South Beach Psychiatric Center', 'Bronx Psychiatric Center', 'Kingsboro Psychiatric Center', 'New York State Psychiatric Institute'}
for i,f in enumerate(F): f["id"]="F%03d"%(i+1); f["rate"]=random.uniform(0.85,1.3)
FID={f["name"]:i for i,f in enumerate(F)}

# name, avoidable, acute share, LOS mean, cost mean, age profile
DX=[("Heart failure",1,6,5,14000,"e"),("COPD and asthma",1,5,4,10500,"e"),("Pneumonia",1,4.5,5,12000,"e"),
("Influenza, COVID-19 and viral respiratory infection",0,3,4,10000,"m"),("Diabetes complications",1,3,4,11000,"m"),
("Hypertension",1,1.5,3,8000,"e"),("Urinary tract infection",1,3,4,9000,"e"),("Sepsis",0,9,7,24000,"e"),
("Coronary artery disease and heart attack",0,5,4,26000,"e"),("Cardiac arrhythmia",0,3.5,3,13000,"e"),("Stroke",0,3.5,6,21000,"e"),
("Gastrointestinal",0,9,4,13000,"m"),("Kidney disease and fluid disorders",0,4,4,11500,"e"),("Mental health",0,5,9,11000,"y"),
("Substance use",0,3.5,5,8500,"y"),("Maternity and newborn",0,11,3,9500,"mat"),("Orthopedic and joint",0,6,3,28000,"m"),
("Cancer",0,4,6,25000,"m"),("Injury and trauma",0,4.5,5,19000,"m"),("Other medical and surgical",0,6,4,15000,"m")]
N=[d[0] for d in DX]; ix={n:i for i,n in enumerate(N)}
HF,COPD,PNA,FLU,DM,HTN,UTI,SEP,CAD,ARR,STR,GI,KID,MH,SUD,MAT,ORT,CA,INJ,OTH=range(20)
def mix(d):
    v=[0.0]*20
    for k,x in d.items(): v[k]=x
    s=sum(v); return [x/s for x in v]
MIX={A:mix({i:DX[i][2] for i in range(20)}),
 C:mix({COPD:18,FLU:20,PNA:8,GI:10,DM:4,MH:6,INJ:8,CA:6,SEP:3,UTI:3,KID:5,OTH:9}),
 P:mix({MH:75,SUD:25}),O:mix({ORT:85,INJ:12,OTH:3}),K:mix({CA:85,SEP:5,OTH:10}),E:mix({OTH:100}),
 L:mix({CA:70,HF:8,OTH:22}),R:mix({STR:40,ORT:30,INJ:20,OTH:10}),T:mix({PNA:20,SEP:20,COPD:15,KID:10,OTH:35}),W:mix({MAT:95,OTH:5})}
AGES=["0-17","18-44","45-64","65-74","75-84","85+"]
AGEP={"e":[1,7,27,25,25,15],"m":[4,20,32,20,16,8],"y":[6,50,36,6,2,0],"mat":[0,100,0,0,0,0]}
# admitting-diagnosis confusion (true -> what it may look like at admission)
CONF={PNA:[SEP,FLU,COPD],FLU:[PNA,COPD],COPD:[PNA,HF],HF:[COPD,ARR,KID],UTI:[SEP,KID],SEP:[PNA,UTI,GI],CAD:[ARR,OTH],
 HTN:[CAD,OTH],ARR:[CAD,HF],KID:[UTI,HF],STR:[OTH],DM:[KID,OTH],GI:[OTH],INJ:[ORT],ORT:[INJ],CA:[OTH],SUD:[MH],MH:[SUD]}

def bump(d):
    doy=d.timetuple().tm_yday; x=min(abs(doy-10),365-abs(doy-10)); return math.exp(-0.5*(x/32.0)**2)
def season(k,d):
    b=bump(d)
    if k==FLU: return 0.55+3.2*b
    if k==PNA: return 0.85+0.6*b
    if k==COPD: return 0.9+0.4*b
    if k==HF: return 0.95+0.2*b
    if k==SEP: return 0.97+0.1*b
    if k==INJ: return 1.1 if d.month in (6,7,8) else 0.97
    return 1.0
WD=[1.08,1.08,1.08,1.08,1.08,0.82,0.78]

D=dt.date
# ICD-10 codes by diagnosis group: [(code, weight for adults, weight for children)]
CODES={n:[] for n in N}
with open(os.path.join(HERE,"..","data","icd10_codes.csv"),newline="") as fh:
    for r in csv.DictReader(fh): CODES[r["diagnosis_group"]].append((r["code"],float(r["weight"]),float(r["weight_children"])))
assert all(CODES[n] for n in N)
def draw_code(group,child,lean=None,extra=0.0):
    # The extra admissions of a planted hotspot lean toward its leading codes,
    # so the code breakdown has something to show.
    rng=code_rng
    if lean and rng.random()<extra:
        r=rng.random(); acc=0.0
        for code,share in lean.items():
            acc+=share
            if r<acc: return code
    rows=CODES[group]
    return rng.choices([c[0] for c in rows],weights=[c[2] if child else c[1] for c in rows])[0]

PL=[]  # id, label, facilities, dx list (None=all), start, end, multiplier fn, should_alert, note, leading codes
def plant(pid,label,facs,dxs,s,e,fn,alert,note,codes=None,extra=False,shape="",replay=""):
    PL.append(dict(id=pid,label=label,f=[FID[x] for x in facs],dx=dxs,s=s,e=e,fn=fn,alert=alert,note=note,codes=codes,extra=extra,shape=shape,replay=replay))
plant("H1","Single facility and diagnosis, sustained shift",["Maimonides Medical Center"],[HF],D(2026,9,6),ASOF,lambda d:3.0,"Yes","One facility x diagnosis alert",{"I50.23":0.7})
plant("H2","Multi-facility wave (rolls up to diagnosis level)",["NYC Health + Hospitals/Elmhurst","NewYork-Presbyterian Queens","Jamaica Hospital Medical Center","Flushing Hospital Medical Center","Long Island Jewish Medical Center","NYC Health + Hospitals/Queens"],[FLU],D(2026,9,6),ASOF,lambda d:[3.0,5.0,7.0,9.0][min(3,(d-D(2026,9,6)).days//7)],"Yes","Climbing week over week; 6 facilities, so one rolled-up diagnosis alert",{"J10.1":0.65,"J10.00":0.2})
plant("H3","One facility elevated across all diagnoses (rolls up to facility level)",["NYC Health + Hospitals/Kings County"],None,D(2026,9,6),ASOF,lambda d:1.8,"Yes","Several diagnosis groups at one facility, so one rolled-up facility alert")
plant("H4","Two facilities, same diagnosis (below rollup minimum)",["NYC Health + Hospitals/Lincoln","BronxCare Hospital Center - Concourse Division"],[COPD],D(2026,9,6),ASOF,lambda d:3.4,"Yes","Two separate facility x diagnosis alerts",{"J45.901":0.7})
plant("H5","One-week spike",["NYU Langone Hospital - Brooklyn"],[GI],D(2026,9,27),ASOF,lambda d:6.0,"Yes","Only the latest-week comparison should fire strongly",{"A09":0.75})
plant("D1","Decoy: large percentage, tiny volume",["Mount Sinai Brooklyn"],[HTN],D(2026,9,6),ASOF,lambda d:3.0,"No","Should be blocked by the minimum excess volume")
plant("P1","Historical hotspot, since resolved",["Montefiore Medical Center - Moses Campus"],[SEP],D(2026,3,1),D(2026,4,11),lambda d:2.2,"No (past)","Visible in the 12-month chart; useful for back-testing",{"A41.51":0.5})
# --- Evaluation patterns added later. Each is extra admissions on top of the file as it was. ---
S6=D(2026,9,6)
plant("H6","Slow climb at one facility and diagnosis",["NYC Health + Hospitals/Bellevue"],[SEP],S6,ASOF,lambda d:[1.4,1.9,2.5,3.2][min(3,(d-S6).days//7)],"Yes","Rises a little more each week; the trend check should catch it",{"A41.9":0.6},extra=True,shape="One alert")
plant("H7","Wave across exactly three facilities in one borough",["The Mount Sinai Hospital","Lenox Hill Hospital","NYU Langone Tisch Hospital"],[UTI],S6,ASOF,lambda d:4.0,"Yes","Three is the minimum for a rolled-up group, so this should be one alert, not three",{"N39.0":0.8},extra=True,shape="One grouped alert")
plant("H8","Specialty hospital, its main diagnosis",["Memorial Sloan Kettering Cancer Center"],[CA],S6,ASOF,lambda d:1.6,"Yes","A modest percentage on a high volume; large in admissions",extra=True,shape="One alert")
plant("H9","Children's hospital",["Cohen Children's Medical Center"],[COPD],S6,ASOF,lambda d:3.2,"Yes","Asthma at a children's hospital",{"J45.901":0.8},extra=True,shape="One alert")
plant("H10","Small facility outside the city, all diagnoses",["Hackensack University Medical Center"],None,S6,ASOF,lambda d:2.4,"Yes","Low volume overall, so only the facility as a whole should qualify",extra=True,shape="One hospital-wide alert")
plant("D2","Decoy: small rise at a large facility",["NewYork-Presbyterian/Weill Cornell Medical Center"],[GI],S6,ASOF,lambda d:1.2,"No","About three extra admissions; within normal ups and downs",extra=True)
plant("D3","Decoy: tiny facility doubles",["Creedmoor Psychiatric Center"],[MH],S6,ASOF,lambda d:2.0,"No","Double, but only about three extra admissions; blocked by the minimum volume",extra=True)
plant("D4","Decoy: spike that ended before the window",["Montefiore Medical Center - Weiler Hospital"],[PNA],D(2026,7,5),D(2026,8,1),lambda d:3.0,"No","Over five weeks ago; nothing is elevated now",extra=True)
plant("D5","Decoy: a single busy day",["St. Barnabas Hospital"],[INJ],D(2026,9,20),D(2026,9,20),lambda d:40.0,"No","One day cannot make a 28-day hotspot",extra=True)
plant("D6","Decoy: two-week bump that faded",["NewYork-Presbyterian Brooklyn Methodist Hospital"],[DM],D(2026,8,9),D(2026,8,22),lambda d:2.5,"No","Ended two weeks before the window; the previous-28-days check should not fire",extra=True)

# --- Patterns for health systems, network status, and membership. Their own stream again. ---
plant("Y1","Same diagnosis at three facilities of one health system, in three boroughs",["Long Island Jewish Medical Center","Lenox Hill Hospital","Staten Island University Hospital - North"],[STR],S6,ASOF,lambda d:4.0,"Yes","No borough has three, so only the health system links them; should be one system-wide hotspot",{"I63.9":0.7},extra=2,shape="One system-wide alert")
plant("Y2","Same diagnosis at two facilities of one health system",["Montefiore Medical Center - Moses Campus","Montefiore Medical Center - Weiler Hospital"],[DM],S6,ASOF,lambda d:4.0,"Yes","Two is below the minimum of three, so they should stay as two separate hotspots",extra=2,shape="Two separate alerts")
plant("Y3","One large and two small facilities of one health system",["NewYork-Presbyterian/Weill Cornell Medical Center","NewYork-Presbyterian Allen Hospital","NewYork-Presbyterian Lower Manhattan Hospital"],[KID],S6,ASOF,lambda d:3.5,"Yes","The small ones are too small to qualify; the large one should still be flagged, with no system group",extra=2,shape="Large facility only")
plant("N1","Hotspot at an out-of-network facility",["Richmond University Medical Center"],[PNA],S6,ASOF,lambda d:4.0,"Yes","Network status is a label only; it must not change detection",extra=2,shape="One alert")
NASSAU=[f["name"] for f in F if f["county"]=="Nassau"]
plant("E1","Enrollment jump: 50% more members in one county",NASSAU,None,S6,ASOF,lambda d:1.5,"Yes","Known limitation. Admissions rise only because membership did; detection counts admissions, so it should flag it, and the screen should show membership up 50%",extra=2,shape="At least one facility")

def mult(fi,k,d):
    m=1.0
    for p in PL:
        if not p["extra"] and p["s"]<=d<=p["e"] and fi in p["f"] and (p["dx"] is None or k in p["dx"]): m*=p["fn"](d)
    return m
def xplant(fi,k,d,stream=1):
    """The later evaluation pattern of one stream active here today, if any (within a stream they never overlap)."""
    for p in PL:
        if int(p["extra"])==stream and p["s"]<=d<=p["e"] and fi in p["f"] and (p["dx"] is None or k in p["dx"]): return p
    return None

def pois(l):
    if l<=0: return 0
    L=math.exp(-l); k=0; p=1.0
    while True:
        p*=random.random()
        if p<=L: return k
        k+=1
def pick(w): return random.choices(range(len(w)),weights=w)[0]

# member pools by age band
pools={}; mid=0; LOB={}
for a,n in zip(AGES,[9000,26000,28000,16000,13000,7000]):
    pools[a]=[]
    for _ in range(n):
        mid+=1; m="M%06d"%mid; pools[a].append(m)
        if a in ("65-74","75-84","85+"): LOB[m]=random.choices(["Medicare Advantage","Medicaid Managed Care","Commercial"],[88,4,8])[0]
        else: LOB[m]=random.choices(["Medicaid Managed Care","Commercial"],[55,45])[0]
def member(a):
    p=pools[a]
    return p[random.randrange(max(1,len(p)//20))] if random.random()<0.25 else random.choice(p)

W=sum(f["w"] for f in F); lastdis={}; xlast={}; ylast={}; rows=[]; aid=0; xid=9000000; yid=9500000; hidden=0; pcount={p["id"]:0 for p in PL}
d=START
while d<=ASOF:
    g=(1+0.04*(d-START).days/365.0)*WD[d.weekday()]
    inwin={p["id"] for p in PL if p["s"]<=d<=p["e"]}
    for fi,f in enumerate(F):
        mx=MIX[f["type"]]; base=DAILY*f["w"]/W*g
        for k in range(20):
            if mx[k]==0: continue
            n=pois(base*mx[k]*season(k,d)*mult(fi,k,d))
            # A planted hotspot with leading codes here, and the share of admissions it added.
            lean=None; extra=0.0
            for p in PL:
                if not p["extra"] and p["codes"] and p["s"]<=d<=p["e"] and fi in p["f"] and (p["dx"] is None or k in p["dx"]):
                    lean=p["codes"]; extra=1-1/p["fn"](d)
            # A later evaluation pattern adds its admissions from its own random stream.
            xp=xplant(fi,k,d); n2=0
            if xp:
                random=xrng; n2=pois(base*mx[k]*season(k,d)*(xp["fn"](d)-1.0)); random=_main
            yp=xplant(fi,k,d,2); n3=0
            if yp:
                random=yrng; n3=pois(base*mx[k]*season(k,d)*(yp["fn"](d)-1.0)); random=_main
            for j in range(n+n2+n3):
                if j==n and n2: random=xrng; code_rng=xcrng; lean=xp["codes"]; extra=1.0
                if j==n+n2 and n3: random=yrng; code_rng=ycrng; lean=yp["codes"]; extra=1.0
                if j<n: aid+=1; rid="A%07d"%aid
                elif j<n+n2: xid+=1; rid="A%07d"%xid
                else: yid+=1; rid="A%07d"%yid
                a="0-17" if f["type"]==C else AGES[pick(AGEP[DX[k][5]])]
                m=member(a)
                losm=DX[k][3]*(3 if f["type"] in (T,R) or f["name"] in LONG_STAY else 1)
                los=max(1,int(round(random.lognormvariate(math.log(losm)-0.18,0.6))))
                dis=d+dt.timedelta(days=los)
                r=random.random()
                lag=0 if r<0.45 else 1 if r<0.80 else 2 if r<0.90 else 3 if r<0.94 else random.randint(4,10) if r<0.98 else None
                notif=d+dt.timedelta(days=lag) if lag is not None else None
                claim=dis+dt.timedelta(days=max(10,int(random.lognormvariate(math.log(32),0.5))))
                seen_n=notif is not None and notif<=ASOF; seen_c=claim<=ASOF
                ld=lastdis if j<n else xlast if j<n+n2 else ylast
                readm="Y" if (m in ld and 0<=(d-ld[m]).days<=30 and k!=MAT) else "N"
                ld[m]=dis
                if not (seen_n or seen_c): hidden+=1; continue
                adm=k if (random.random()<0.88 or k not in CONF) else random.choice(CONF[k])
                if k==MAT: at=random.choices(["Emergency","Scheduled"],[70,30])[0]
                elif k==ORT: at=random.choices(["Emergency","Scheduled"],[35,65])[0]
                elif k==CA: at=random.choices(["Emergency","Scheduled","Transfer"],[55,40,5])[0]
                else: at=random.choices(["Emergency","Direct","Transfer"],[88,7,5])[0]
                paid=DX[k][4]*f["rate"]*random.lognormvariate(-0.1,0.45)*(0.6+0.4*los/losm)
                best=k if seen_c else adm
                code=draw_code(N[best],a=="0-17",lean if best==k else None,extra)
                for p in PL:
                    if p["id"] in inwin and fi in p["f"] and (p["dx"] is None or k in p["dx"]): pcount[p["id"]]+=1
                rows.append([rid,m,LOB[m],a,f["id"],f["name"],TYPE_LABEL[f["type"]],f["borough"],f["county"],d.isoformat(),
                    dis.isoformat() if dis<=ASOF else "", los if dis<=ASOF else "", at, N[adm], N[k] if seen_c else "",
                    N[best], code, "Y" if DX[best][1] else "N", readm, notif.isoformat() if seen_n else "",
                    claim.isoformat() if seen_c else "", "Paid" if seen_c else "Not received", "%.2f"%paid if seen_c else ""])
            random=_main; code_rng=crng
    d+=dt.timedelta(days=1)

H=["admission_id","member_id","line_of_business","age_band","facility_id","facility_name","facility_type","borough","county","admit_date",
"discharge_date","length_of_stay","admission_type","admitting_diagnosis_group","final_diagnosis_group","diagnosis_group","diagnosis_code","potentially_avoidable",
"readmission_30d","notification_date","claim_received_date","claim_status","paid_amount"]
with open(os.path.join(OUT,"synthetic_admissions.csv"),"w",newline="") as fh:
    w=csv.writer(fh); w.writerow(H); w.writerows(rows)
# Cases that plant nothing: they replay detection on an earlier date, or check a rule.
CHECKS=[
 ("R1","Replay: the March sepsis hotspot, seen while it was happening","Montefiore Medical Center - Moses Campus","Sepsis","2026-03-01","2026-04-11","Yes","Run as of April 4, 2026, detection should flag it","One alert","2026-04-04"),
 ("R2","Replay: the same facility today","Montefiore Medical Center - Moses Campus","Sepsis","2026-03-01","2026-04-11","No","It ended in April; nothing should be flagged now","",""),
 ("R3","Replay: flu season at its January peak","Plan-wide","Influenza, COVID-19 and viral respiratory infection","2026-01-01","2026-01-17","No","Flu is high every January, so the season by itself is not a hotspot","No plan-wide alert","2026-01-17"),
 ("R4","Replay: a week before the September patterns begin","Maimonides Medical Center; NYC Health + Hospitals/Kings County; NYU Langone Hospital - Brooklyn; NYC Health + Hospitals/Bellevue; Memorial Sloan Kettering Cancer Center","Their planted diagnoses","2026-08-02","2026-08-29","No","None of these should be flagged before its pattern starts","","2026-08-29"),
 ("R5","Replay: one week into the Queens flu wave","NYC Health + Hospitals/Elmhurst; NewYork-Presbyterian Queens; Jamaica Hospital Medical Center; Flushing Hospital Medical Center; Long Island Jewish Medical Center; NYC Health + Hospitals/Queens","Influenza, COVID-19 and viral respiratory infection","2026-09-06","2026-09-12","Yes","How early is it caught? After one week at least one of the six should be flagged","At least one facility","2026-09-12"),
 ("S1","Rule: the top list is never longer than 10","Plan-wide","All","","","Yes","However many alerts qualify, at most 10 are marked as top hotspots","At most 10",""),
 ("S2","Rule: one event is listed once","NYC Health + Hospitals/Kings County","All","2026-09-06","2026-10-03","Yes","Kings County is one alert, not one per diagnosis group","Exactly one alert",""),
 ("S3","Rule: every alert clears the minimum volume","Plan-wide","All","","","Yes","No alert is fewer than 6 admissions above expected","All alerts",""),
]
with open(os.path.join(OUT,"planted_hotspots_answer_key.csv"),"w",newline="") as fh:
    w=csv.writer(fh); w.writerow(["id","pattern","facilities","diagnosis_group","start_date","end_date","should_alert","admissions_in_period","note","leading_codes","expected_shape","replay_as_of"])
    for p in PL:
        w.writerow([p["id"],p["label"],"; ".join(F[i]["name"] for i in p["f"]),"All" if p["dx"] is None else "; ".join(N[k] for k in p["dx"]),p["s"],p["e"],p["alert"],pcount[p["id"]],p["note"],"; ".join(p["codes"]) if p["codes"] else "",p["shape"],p["replay"]])
    for c in CHECKS:
        w.writerow([c[0],c[1],c[2],c[3],c[4],c[5],c[6],"",c[7],"",c[8],c[9]])
# Members living in each area (a borough, or a county outside the city), now and a year
# ago. The plan grew about 4% everywhere, except the county in pattern E1.
area_of=lambda f: f["borough"] if f["borough"]!="Outside NYC" else (f["county"].replace(" (NJ)"," County, NJ") if "(NJ)" in f["county"] else f["county"]+" County")
weight={}
for f in F: weight[area_of(f)]=weight.get(area_of(f),0)+f["w"]
with open(os.path.join(OUT,"membership_by_area.csv"),"w",newline="") as fh:
    w=csv.writer(fh); w.writerow(["area","members","members_year_ago"])
    for a in sorted(weight):
        now=int(round(99000*weight[a]/W/10.0))*10
        w.writerow([a,now,int(round(now/(1.5 if a=="Nassau County" else 1.04)/10.0))*10])
print("rows",len(rows),"not yet reported",hidden,"members",len({r[1] for r in rows}),"facilities",len({r[4] for r in rows}))
