"""Reviewable HSV colour-area segmentation, not a trained diagnostic model."""
from PIL import Image, ImageOps, ImageDraw
import numpy as np
import io, hashlib, base64, uuid, json
from research import number

def measure(body, folder):
    try:raw=base64.b64decode(body.get('image','').split(',')[-1],validate=True)
    except Exception:raise ValueError('Invalid image data.')
    if len(raw)>30_000_000:raise ValueError('Use a field image under 30 MB.')
    try:
        image=Image.open(io.BytesIO(raw))
        if image.format not in ['JPEG','PNG','TIFF']:raise ValueError('Use JPEG, PNG or TIFF.')
        if getattr(image,'n_frames',1)>1:raise ValueError('Export a single field from multi-page or whole-slide TIFF files.')
        if image.width*image.height>20_000_000:raise ValueError('Use an image up to 20 megapixels. Export a field from a whole-slide image.')
        image=ImageOps.exif_transpose(image)
        if image.mode in ['RGBA','LA'] or 'transparency' in image.info:
            image=image.convert('RGBA');bg=Image.new('RGBA',image.size,'white');bg.alpha_composite(image);image=bg.convert('RGB')
        else:image=image.convert('RGB')
    except ValueError:raise
    except Exception:raise ValueError('The selected file cannot be decoded as a supported image.')
    w,h=image.size
    defaults={'background':245,'saturation':35,'dark':25,'blueLow':170,'blueHigh':270,'pinkLow':285,'pinkHigh':25}
    settings={k:number(body.get('settings',{}).get(k,v),0,360 if 'Low' in k or 'High' in k else 255,True) for k,v in defaults.items()}
    if any(v is None for v in settings.values()):raise ValueError('All threshold settings are required.')
    if settings['blueLow']>=settings['blueHigh']:raise ValueError('Blue lower hue must be below blue upper hue.')
    def hue_test(x,lo,hi):return (x>=lo)&(x<=hi) if lo<=hi else ((x>=lo)|(x<=hi))
    hues=np.arange(360)
    if np.any(hue_test(hues,settings['blueLow'],settings['blueHigh']) & hue_test(hues,settings['pinkLow'],settings['pinkHigh'])):raise ValueError('Pink and blue hue intervals must not overlap.')
    mask=Image.new('L',(w,h),0);draw=ImageDraw.Draw(mask)
    roi=body.get('roi')
    def rect(v):
        if not isinstance(v,list) or len(v)!=4:raise ValueError('Invalid selection rectangle.')
        a=[number(x,0,1) for x in v]
        if any(x is None for x in a) or a[2]<=a[0] or a[3]<=a[1]:raise ValueError('Draw a non-empty selection rectangle.')
        return (int(a[0]*w),int(a[1]*h),max(int(a[0]*w),int(a[2]*w)-1),max(int(a[1]*h),int(a[3]*h)-1))
    draw.rectangle(rect(roi) if roi else (0,0,w-1,h-1),fill=255)
    excludes=body.get('excludes',[])
    if len(excludes)>100:raise ValueError('Too many exclusion rectangles.')
    for ex in excludes:draw.rectangle(rect(ex),fill=0)
    rgb=np.asarray(image);hsv=np.asarray(image.convert('HSV'));hue=hsv[:,:,0].astype(float)*360/255
    eligible=(np.asarray(mask)>0)&~np.all(rgb>=settings['background'],axis=2)
    coloured=eligible&(hsv[:,:,1]>=settings['saturation'])&(hsv[:,:,2]>=settings['dark'])
    blue=coloured&hue_test(hue,settings['blueLow'],settings['blueHigh']);pink=coloured&hue_test(hue,settings['pinkLow'],settings['pinkHigh'])
    count=int(eligible.sum())
    if not count:raise ValueError('No eligible tissue remains. Review the selection and background threshold.')
    b=int(blue.sum());p=int(pink.sum());overlay=rgb.copy()
    overlay[~eligible]=(rgb[~eligible]*.25+255*.75).astype('uint8')
    overlay[blue]=[24,127,235];overlay[pink]=[239,69,137]
    codes=np.zeros((h,w),dtype=np.uint8);codes[eligible]=1;codes[blue]=2;codes[pink]=3
    ident=uuid.uuid4().hex;folder.mkdir(exist_ok=True)
    (folder/(ident+'.original')).write_bytes(raw)
    image.save(folder/(ident+'.png'))
    Image.fromarray(overlay).save(folder/(ident+'.overlay.png'))
    Image.fromarray(codes).save(folder/(ident+'.mask.png'))
    result={'asset':ident,'filename':str(body.get('filename','image'))[:200],'width':w,'height':h,'sha256':hashlib.sha256(raw).hexdigest(),'bluePixels':b,'pinkPixels':p,'eligible':count,'otherPixels':count-b-p,'blue':100*b/count,'pink':100*p/count,'settings':settings,'roi':roi,'excludes':excludes,'method':'HSV thresholds v1','source':'image'}
    (folder/(ident+'.json')).write_text(json.dumps(result),encoding='utf-8')
    return result
