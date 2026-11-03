import math, itertools, warnings
import numpy as np
from scipy import stats
import statsmodels.api as sm

VERSION = '1.0.0'
REGIONS = ['Pseudocapsule', 'Periphery', 'Core', 'Myometrium']
DOMAINS = {
    'Symptom severity': list(range(1, 9)),
    'Concern': [9,15,22,28,32],
    'Activities': [10,11,13,19,20,27,29],
    'Energy / mood': [12,17,23,24,25,31,35],
    'Control': [14,16,26,30,34],
    'Self-consciousness': [18,21,33],
    'Sexual function': [36,37]
}
WEIGHTS = [1,5,20,1,5,10,1,5,1]

def number(x, lower=None, upper=None, integer=False):
    if x is None or x == '': return None
    if isinstance(x,bool): raise ValueError('A numeric value is required.')
    try: x = float(x)
    except (TypeError,ValueError): raise ValueError('A numeric value is required.')
    if not math.isfinite(x) or (lower is not None and x < lower) or (upper is not None and x > upper):
        raise ValueError('Numeric value is outside its allowed range.')
    if integer and x != int(x): raise ValueError('A whole-number value is required.')
    return int(x) if integer else x

def ufs_score(answers, confirmed=False):
    if len(answers)!=37: raise ValueError('UFS-QOL requires 37 numbered responses.')
    values=[number(v,1,5,True) for v in answers]
    result={}; raw_total=0; total_valid=True
    for name,items in DOMAINS.items():
        present=[values[i-1] for i in items if values[i-1] is not None]
        missing=len(items)-len(present)
        raw=None; score=None
        if missing < len(items)/2:
            raw=sum(present)/len(present)*len(items)
            score=(raw-len(items))/(4*len(items))*100 if name=='Symptom severity' else (5*len(items)-raw)/(4*len(items))*100
        result[name]={'score':score,'answered':len(present),'items':len(items),'imputed':missing if raw is not None else 0,'raw':raw}
        if name!='Symptom severity':
            if raw is None: total_valid=False
            else: raw_total+=raw
    result['HRQL total']={'score':(145-raw_total)/116*100 if total_valid else None,'answered':sum(x is not None for x in values[8:]),'items':29,'imputed':sum(v['imputed'] for k,v in result.items() if k!='Symptom severity'),'raw':raw_total if total_valid else None}
    return {'domains':result,'confirmed':confirmed,'version':'Original 37-item / six HRQL domains','answers':values}

APPENDIX_DOMAINS = {'Symptom Severity': (0,8), 'Concern': (8,15), 'Activities': (15,21), 'Energy/Mood': (21,27), 'Control': (27,32), 'Sexual Function': (32,37)}

def appendix_score(answers):
    if not isinstance(answers,list) or len(answers)!=37: raise ValueError('Appendix D requires 37 responses.')
    values=[number(v,1,5,True) for v in answers]
    domains={}
    for name,(start,end) in APPENDIX_DOMAINS.items():
        part=values[start:end]
        domains[name]=sum(part) if all(v is not None for v in part) else None
    return {'domains':domains,'composite':sum(domains.values()) if all(v is not None for v in domains.values()) else None,'answered':sum(v is not None for v in values),'version':'Appendix D supplied study form'}

def pbac_score(days, complete=False):
    if not isinstance(days,list) or len(days)>62: raise ValueError('Invalid cycle diary.')
    subtotal=0; missing=False; entered=0; daily=[]
    for row in days:
        if not isinstance(row,list) or len(row)!=9: raise ValueError('Nine counts are required for each day.')
        row=[number(x,0,10000,True) for x in row]
        if all(x is None for x in row): daily.append(None); continue
        entered+=1
        if any(x is None for x in row): missing=True
        val=sum((x or 0)*w for x,w in zip(row,WEIGHTS));subtotal+=val;daily.append(val)
    valid=bool(complete and entered and not missing)
    return {'subtotal':subtotal,'score':subtotal if valid else None,'complete':valid,'enteredDays':entered,'incompleteRows':missing,'daily':daily,'heavyBleeding':subtotal>100 if valid else None,'threshold':'>100','weights':WEIGHTS}

def validate_participant(p):
    import re
    if not isinstance(p,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',p.get('id','')): raise ValueError('Study ID must contain 1–50 letters, numbers, underscores or hyphens.')
    for key,lo,hi,integer in [('age',25,55,True),('vitaminD',0,1000,False),('parity',0,30,True),('bmi',5,100,False),('hemoglobin',0,30,False),('size',0,100,False),('width',0,100,False),('depth',0,100,False)]:
        p[key]=number(p.get(key),lo,hi,integer)
    if p.get('location','') not in ['', 'Submucosal','Intramural','Subserosal','Other']: raise ValueError('Invalid fibroid location.')
    if p.get('multiplicity','') not in ['', 'Single','Multiple']: raise ValueError('Invalid fibroid multiplicity.')
    if len(p.get('notes',''))>5000: raise ValueError('Notes are too long.')
    for m in p.get('measurements',[]):
        if m.get('region') not in REGIONS or m.get('reviewer') not in ['A','B']: raise ValueError('Invalid measurement region or reviewer.')
        if m.get('source') not in ['manual','image']: raise ValueError('Invalid measurement source.')
        m['blue']=number(m.get('blue'),0,100);m['pink']=number(m.get('pink'),0,100)
        if m['blue'] is None or m['pink'] is None: raise ValueError('Both blue and pink percentages are required.')
        if m['blue']+m['pink']>100.00001: raise ValueError('Pink and blue cannot exceed 100% of eligible tissue.')
        m['eligible']=number(m.get('eligible'),1,None,True)
        if not str(m.get('field','')).strip(): raise ValueError('A field identifier is required.')
        if len(str(m.get('field','')))>100: raise ValueError('Field identifier is too long.')
    keys=[(m['region'],m['reviewer'],m['field']) for m in p.get('measurements',[])]
    if len(keys)!=len(set(keys)): raise ValueError('Each region/reviewer/field combination must be unique.')
    image_keys=[(m['region'],m['reviewer'],m.get('sha256'),str(m.get('roi')),str(m.get('excludes'))) for m in p.get('measurements',[]) if m['source']=='image']
    if len(image_keys)!=len(set(image_keys)):raise ValueError('This exact image selection is already saved for this region and reviewer.')
    if 'pbac' in p:
        b=p['pbac'];b['result']=pbac_score(b['days'],bool(b.get('complete')))
    if 'ufs' in p:
        u=p['ufs'];u['result']=ufs_score(u['answers'],bool(u.get('confirmed')))
    if 'appendixD' in p:
        u=p['appendixD'];u['result']=appendix_score(u['answers'])
    return p

def aggregate(p,region,reviewer='A'):
    ms=[m for m in p.get('measurements',[]) if m['region']==region and m['reviewer']==reviewer]
    if not ms:return None
    weighted=all(m.get('eligible') for m in ms)
    weights=[m['eligible'] if weighted else 1 for m in ms]
    return {'blue':sum(m['blue']*w for m,w in zip(ms,weights))/sum(weights),'pink':sum(m['pink']*w for m,w in zip(ms,weights))/sum(weights),'fields':len(ms),'method':'Tissue-area weighted' if weighted else 'Equal field weights (area unavailable)'}

def flat(p,reviewer='A'):
    row={k:p.get(k) for k in ['id','age','parity','bmi','vitaminD','hemoglobin','size','location','multiplicity']}
    row['volume']=math.pi/6*p['size']*p['width']*p['depth'] if all(p.get(k) for k in ['size','width','depth']) else None
    row['vitaminStatus']=None if row['vitaminD'] is None else ('Deficient' if row['vitaminD']<20 else 'Insufficient' if row['vitaminD']<30 else 'Sufficient')
    row['sizeGroup']=None if row['size'] is None else ('≤5 cm' if row['size']<=5 else '>5 cm')
    for r in REGIONS:
        a=aggregate(p,r,reviewer);row[r]=a['blue'] if a else None
    row['pbac']=pbac_score(p['pbac']['days'],p['pbac'].get('complete',False))['score'] if 'pbac' in p else None
    row['bleedingGroup']=None if row['pbac'] is None else ('>100' if row['pbac']>100 else '≤100')
    u=ufs_score(p['ufs']['answers'],p['ufs'].get('confirmed',False)) if 'ufs' in p else None
    for k in list(DOMAINS)+['HRQL total']:
        row[k]=u['domains'][k]['score'] if u and u['confirmed'] else None
    appendix=appendix_score(p['appendixD']['answers']) if 'appendixD' in p else None
    row['Appendix D date']=p.get('appendixD',{}).get('date')
    for name in APPENDIX_DOMAINS:
        row['Appendix D '+name]=appendix['domains'][name] if appendix else None
    row['Appendix D composite']=appendix['composite'] if appendix else None
    for i in range(37):
        row['Appendix D item '+str(i+1)]=p['appendixD']['answers'][i] if appendix else None
    return row

def clean(obj):
    if isinstance(obj,dict):return {k:clean(v) for k,v in obj.items()}
    if isinstance(obj,(list,tuple,np.ndarray)):return [clean(x) for x in obj]
    if isinstance(obj,(float,np.floating)):return float(obj) if np.isfinite(obj) else None
    if isinstance(obj,np.integer):return int(obj)
    if isinstance(obj,np.bool_):return bool(obj)
    return obj

def describe(values):
    v=np.array([x for x in values if x is not None],float);n=len(v)
    out={'n':n,'missing':len(values)-n}
    if not n:return out
    out.update(mean=np.mean(v),sd=np.std(v,ddof=1) if n>1 else None,median=np.median(v),q1=np.percentile(v,25),q3=np.percentile(v,75),minimum=min(v),maximum=max(v))
    if 3<=n<=5000 and np.ptp(v)>0:
        s=stats.shapiro(v);out.update(shapiroW=s.statistic,shapiroP=s.pvalue)
    return out

def correlation(rows,xkey,ykey,method='spearman'):
    pairs=[(r[xkey],r[ykey]) for r in rows if r.get(xkey) is not None and r.get(ykey) is not None];n=len(pairs)
    result={'x':xkey,'y':ykey,'n':n,'method':method,'points':pairs}
    if n<4:return dict(result,note='At least 4 complete participants required.')
    a=np.array(pairs);x=a[:,0];y=a[:,1]
    if not np.ptp(x) or not np.ptp(y):return dict(result,note='Correlation undefined: at least one variable is constant.')
    f=stats.pearsonr if method=='pearson' else stats.spearmanr
    fit=f(x,y);result.update(coefficient=fit.statistic,p=fit.pvalue)
    if method=='pearson':
        ci=fit.confidence_interval();result['ci']=[ci.low,ci.high];result['ciMethod']='Fisher transformation'
    else:
        # Fixed RNG makes the percentile interval reproducible across report refreshes.
        rng=np.random.default_rng(814);ids=rng.integers(0,n,(1000,n))
        bx=stats.rankdata(x[ids],axis=1);by=stats.rankdata(y[ids],axis=1)
        bx-=bx.mean(axis=1,keepdims=True);by-=by.mean(axis=1,keepdims=True)
        denb=np.linalg.norm(bx,axis=1)*np.linalg.norm(by,axis=1);valid=denb>0
        bs=(bx[valid]*by[valid]).sum(axis=1)/denb[valid]
        result['ci']=np.percentile(bs,[2.5,97.5]) if len(bs) else None;result['ciMethod']='1000-resample percentile bootstrap'
        # Monte Carlo permutation uses rank Pearson equivalence and includes the observed statistic.
        xr=stats.rankdata(x);yr=stats.rankdata(y);xr-=xr.mean();yr-=yr.mean();den=np.linalg.norm(xr)*np.linalg.norm(yr)
        permutations=np.array([rng.permutation(yr) for _ in range(9999)])
        result['p']=(1+np.sum(np.abs(permutations@xr/den)>=abs(fit.statistic)-1e-12))/10000
        result['pMethod']='9999-permutation, two-sided'
    return result

def holm(ps):
    order=np.argsort(ps);out=[0.]*len(ps);prev=0
    for j,i in enumerate(order):prev=max(prev,min(1,(len(ps)-j)*ps[i]));out[i]=prev
    return out

def zonal(rows,method):
    a=np.array([[r[z] for z in REGIONS] for r in rows if all(r[z] is not None for z in REGIONS)],float)
    out={'method':method,'n':len(a),'excluded':len(rows)-len(a),'posthoc':[]}
    if len(a)<3:return dict(out,note='At least 3 participants with all four regions are required.')
    n,k=a.shape
    if method=='friedman':
        if np.all(np.ptp(a,axis=1)==0):return dict(out,note='All four region values are identical within every participant.')
        fit=stats.friedmanchisquare(*a.T)
        ranks=stats.rankdata(a,axis=1);rng=np.random.default_rng(287)
        # Within-participant label permutations preserve ties and pairing.
        rank_ss=np.sum((ranks-(k+1)/2)**2)
        correction=rank_ss/(n*k*(k*k-1)/12)
        permutations=np.argsort(rng.random((9999,n,k)),axis=2)
        sums=np.take_along_axis(np.broadcast_to(ranks,(9999,n,k)),permutations,axis=2).sum(axis=1)
        q=(12/(n*k*(k+1))*np.sum(sums*sums,axis=1)-3*n*(k+1))/correction
        perm_p=(1+np.sum(q>=fit.statistic-1e-10))/10000
        out.update(statistic=fit.statistic,p=perm_p,asymptoticP=fit.pvalue,df=k-1,kendallW=fit.statistic/(n*(k-1)))
        out['note']='Reported p-value uses 9999 within-participant label permutations (seed 287). The asymptotic p-value is retained in the full results export.'
    else:
        grand=a.mean();ss_region=n*np.sum((a.mean(0)-grand)**2);ss_subject=k*np.sum((a.mean(1)-grand)**2)
        ss_error=np.sum((a-grand)**2)-ss_region-ss_subject;df1=k-1;df2=(n-1)*(k-1)
        if ss_error<=1e-12:return dict(out,note='Residual variance is zero; the ANOVA F-test is undefined.')
        f=(ss_region/df1)/(ss_error/df2)
        cov=np.cov(a,rowvar=False);c=np.eye(k)-np.ones((k,k))/k;projected=c@cov@c
        denom=(k-1)*np.trace(projected@projected);eps=np.clip(np.trace(projected)**2/denom,1/(k-1),1) if denom else 1
        out.update(statistic=f,df=[df1,df2],uncorrectedP=stats.f.sf(f,df1,df2),p=stats.f.sf(f,eps*df1,eps*df2),epsilon=eps,partialEtaSquared=ss_region/(ss_region+ss_error))
        out['note']='Reported p-value uses Greenhouse–Geisser correction; assess paired differences and residuals.'
    ps=[]
    for i,j in itertools.combinations(range(k),2):
        d=a[:,i]-a[:,j]
        if np.all(d==0):v=0.;p=1.
        elif method=='friedman':fit=stats.wilcoxon(d,method='auto');v=fit.statistic;p=fit.pvalue
        else:fit=stats.ttest_rel(a[:,i],a[:,j]);v=fit.statistic;p=fit.pvalue
        ps.append(p);out['posthoc'].append({'regions':[REGIONS[i],REGIONS[j]],'statistic':v,'p':p,'meanDifference':np.mean(d),'test':'Wilcoxon signed-rank' if method=='friedman' else 'Paired t-test'})
    for item,p in zip(out['posthoc'],holm(ps)):item['holmP']=p
    return out

def icc_value(a):
    n,k=a.shape;g=a.mean();msr=k*np.sum((a.mean(1)-g)**2)/(n-1);msc=n*np.sum((a.mean(0)-g)**2)/(k-1)
    mse=np.sum((a-a.mean(1)[:,None]-a.mean(0)+g)**2)/((n-1)*(k-1))
    den=msr+(k-1)*mse+k*(msc-mse)/n
    return (msr-mse)/den if abs(den)>1e-12 else np.nan

def agreement(ps):
    result=[]
    for region in REGIONS:
        a=[]
        for p in ps:
            aa=aggregate(p,region,'A');bb=aggregate(p,region,'B')
            if aa and bb:a.append([aa['blue'],bb['blue']])
        out={'region':region,'n':len(a)}
        if len(a)>=3:
            a=np.array(a);d=a[:,0]-a[:,1];bias=d.mean();sd=d.std(ddof=1)
            out.update(icc=icc_value(a),bias=bias,limits=[bias-1.96*sd,bias+1.96*sd],points=np.column_stack([a.mean(1),d]))
            if len(a)>=6:
                rng=np.random.default_rng(174);b=[icc_value(a[rng.integers(0,len(a),len(a))]) for _ in range(1000)];b=[v for v in b if np.isfinite(v)]
                out['ci']=np.percentile(b,[2.5,97.5]) if b else None
        result.append(out)
    return result

def regression(rows,outcome,predictors):
    allowed=['vitaminD','age','bmi','parity','size','Pseudocapsule']
    if outcome not in ['pbac','Symptom severity','HRQL total'] or not predictors or len(set(predictors))!=len(predictors) or any(x not in allowed for x in predictors): raise ValueError('Invalid regression selection.')
    usable=[r for r in rows if all(r.get(k) is not None for k in predictors+[outcome])];n=len(usable)
    result={'outcome':outcome,'predictors':predictors,'n':n,'excluded':len(rows)-n}
    if n<len(predictors)+4:return dict(result,note='Insufficient complete participants for this model. At least predictors + 4 required.')
    x=sm.add_constant(np.array([[r[k] for k in predictors] for r in usable]),has_constant='add');y=np.array([r[outcome] for r in usable])
    if np.linalg.matrix_rank(x)<x.shape[1] or not np.ptp(y):return dict(result,note='Model unavailable: constant outcome or collinear predictors.')
    fit=sm.OLS(y,x).fit();ci=fit.conf_int()
    result.update(rSquared=fit.rsquared,adjustedRSquared=fit.rsquared_adj,residuals=fit.resid.tolist(),fitted=fit.fittedvalues.tolist(),residualNormality=describe(fit.resid),conditionNumber=fit.condition_number,coefficients=[{'term':k,'estimate':fit.params[i],'se':fit.bse[i],'p':fit.pvalues[i],'ci':ci[i]} for i,k in enumerate(['Intercept']+predictors)])
    result['note']='Exploratory association only; not a validated predictive model. '+('Few participants relative to predictors; estimates may be unstable.' if n<10*len(predictors) else 'Review residual plots and model assumptions.')
    return result

def analysis(ps,options):
    reviewer=options.get('reviewer','A')
    if reviewer not in ['A','B']:raise ValueError('Select reviewer A or B.')
    rows=[flat(p,reviewer) for p in ps];method=options.get('correlation','spearman');zm=options.get('zonal','friedman')
    if method not in ['pearson','spearman'] or zm not in ['friedman','anova']:raise ValueError('Invalid analysis method.')
    numeric=['age','parity','bmi','vitaminD','hemoglobin','size','volume','pbac']+list(DOMAINS)+['HRQL total']+REGIONS
    desc={k:describe([r.get(k) for r in rows]) for k in numeric}
    cats={}
    for k in ['location','multiplicity','vitaminStatus','sizeGroup','bleedingGroup']:
        present=[r[k] for r in rows if r.get(k)];cats[k]={'n':len(present),'missing':len(rows)-len(present),'counts':{v:present.count(v) for v in sorted(set(present))}}
    correlations=[correlation(rows,'vitaminD','Pseudocapsule',method)]
    for y in ['pbac']+list(DOMAINS)+['HRQL total']:
        correlations.append(correlation(rows,'vitaminD',y,method))
        for region in REGIONS:correlations.append(correlation(rows,region,y,method))
    valid=[r for r in correlations[1:] if r.get('p') is not None]
    for item,p in zip(valid,holm([r['p'] for r in valid])):item['holmP']=p
    # Subgroups are descriptive/hypothesis-generating and deliberately use rank-based tests.
    subgroup=[]
    for key in ['vitaminStatus','sizeGroup','multiplicity','location','bleedingGroup']:
        groups={}
        for row in rows:
            if row.get(key) and row['Pseudocapsule'] is not None:groups.setdefault(row[key],[]).append(row['Pseudocapsule'])
        item={'group':key,'summaries':{k:describe(v) for k,v in groups.items()}}
        if len(groups)>=2 and all(len(v)>=2 for v in groups.values()) and np.ptp([v for a in groups.values() for v in a]):
            fit=stats.kruskal(*groups.values());item.update(statistic=fit.statistic,p=fit.pvalue,test='Kruskal–Wallis')
        subgroup.append(item)
    valid=[r for r in subgroup if 'p' in r]
    for item,p in zip(valid,holm([r['p'] for r in valid])):item['holmP']=p
    warnings_list=[]
    if any(aggregate(p,r,reviewer) and 'Equal' in aggregate(p,r,reviewer)['method'] for p in ps for r in REGIONS):warnings_list.append('Some regions use equal field weights because tissue pixel counts are unavailable. Review aggregation before final analysis.')
    if any(m['source']=='image' for p in ps for m in p.get('measurements',[])):warnings_list.append('Colour-threshold measurements are preliminary until validated against pathologist/ImageJ reference measurements.')
    image_settings={str(sorted(m.get('settings',{}).items())) for p in ps for m in p.get('measurements',[]) if m['source']=='image'}
    if len(image_settings)>1:warnings_list.append('Multiple image threshold settings were used. Review measurement consistency.')
    recall_periods={p['ufs'].get('recall','Unspecified') for p in ps if p.get('ufs',{}).get('confirmed')}
    if len(recall_periods)>1:warnings_list.append('More than one UFS-QOL recall period is present. Review comparability before pooling these responses.')
    warnings_list.append('No ordinal fibrosis-grade analysis is produced: the protocol does not define a grading scale. Continuous collagen fractions are analysed.')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        output={'version':VERSION,'n':len(rows),'reviewer':reviewer,'rows':rows,'descriptive':desc,'categorical':cats,'correlations':correlations,'zonal':zonal(rows,zm),'agreement':agreement(ps),'subgroups':subgroup,'warnings':warnings_list,'regression':regression(rows,options.get('outcome','pbac'),options.get('predictors',['vitaminD']))}
    return clean(output)
