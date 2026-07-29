#!/usr/bin/env python3
import json, re, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'weather.json'
CITIES={
 'Москва':('208010100','Europe/Moscow'),
 'Баюйцюань / Инкоу':('101070806','Asia/Shanghai'),
 'Туаньшань / Бэйхай':('101070806','Asia/Shanghai'),
 'Далянь':('101070201','Asia/Shanghai'),
 'Пекин':('101010100','Asia/Shanghai'),
 'Великая Китайская стена / Пекин':('101010100','Asia/Shanghai')
}
TRANSLATE={'晴':'Ясно','多云':'Переменная облачность','阴':'Пасмурно','小雨':'Небольшой дождь','中雨':'Дождь','大雨':'Сильный дождь','暴雨':'Ливень','阵雨':'Кратковременный дождь','雷阵雨':'Гроза с дождём','小雪':'Небольшой снег','中雪':'Снег','大雪':'Сильный снег','雾':'Туман','霾':'Дымка'}
CODE={'00':0,'01':2,'02':3,'03':51,'04':95,'07':61,'08':63,'09':65,'10':65,'13':71,'14':73,'15':75,'18':45,'53':48}

def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.weather.com.cn/'})
    return urllib.request.urlopen(req,timeout=25).read().decode('utf-8','replace')

def variable(text,name):
    m=re.search(r'var\s+'+re.escape(name)+r'\s*=\s*(\{.*?\})(?:;|\r?\n)',text,re.S)
    if not m: raise ValueError(name)
    return json.loads(m.group(1))

def iso_hour(raw,now):
    m=re.match(r'(\d{2})日(\d{2})时',raw)
    day,hour=map(int,m.groups()); month=now.month; year=now.year
    if day < now.day-15:
        month+=1
        if month==13: month=1; year+=1
    elif day > now.day+15:
        month-=1
        if month==0: month=12; year-=1
    return f'{year:04d}-{month:02d}-{day:02d}T{hour:02d}:00'

def city(name,code,tz):
    index=fetch(f'https://d1.weather.com.cn/weather_index/{code}.html')
    page=fetch(f'https://www.weather.com.cn/weather1d/{code}.shtml')
    try: current=variable(index,'dataSK')
    except ValueError: current=None
    try: hours=variable(page,'hour3data')
    except ValueError: hours={}
    now=datetime.now(ZoneInfo(tz)); hourly=[]; seen=set()
    groups=[hours.get('1d',[])]+hours.get('23d',[])+hours.get('7d',[])
    for group in groups:
        for raw in group:
            parts=raw.split(',')
            if len(parts)<6: continue
            stamp=iso_hour(parts[0],now)
            if stamp in seen: continue
            seen.add(stamp)
            cn=parts[2]; code_raw=re.sub(r'^[dn]','',parts[1])
            hourly.append({'time':stamp,'temperature':float(parts[3].replace('℃','')),
              'weather_cn':cn,'weather':TRANSLATE.get(cn,cn),'weather_code':CODE.get(code_raw,3),
              'wind_direction':parts[4],'wind_level':parts[5],'precipitation_probability':None})
    hourly.sort(key=lambda x:x['time'])
    if current:
        wind_kmh=float(re.sub(r'[^0-9.]','',current.get('wse','0')) or 0); humidity=float(re.sub(r'[^0-9.]','',current.get('SD','0')) or 0); cn=current.get('weather',''); temp=float(current.get('temp') or 0); rain=float(current.get('rain') or 0); raw_code=re.sub(r'^[dn]','',current.get('weathercode',''))
    else:
        nearest=min(hourly,key=lambda x:abs(datetime.fromisoformat(x['time']).replace(tzinfo=ZoneInfo(tz))-now)) if hourly else {'temperature':0,'weather_cn':'','weather_code':3}
        wind_kmh=0; humidity=0; cn=nearest['weather_cn']; temp=nearest['temperature']; rain=0; raw_code=''
    return name,{'station_code':code,'source_url':f'https://www.weather.com.cn/weather1d/{code}.shtml',
      'current':{'time':now.isoformat(timespec='minutes'),'temperature':temp,
        'apparent_temperature':None,'humidity':humidity,'wind_kmh':wind_kmh,
        'weather_cn':cn,'weather':TRANSLATE.get(cn,cn),'weather_code':CODE.get(raw_code,nearest.get('weather_code',3) if not current else 3),
        'rain_mm':rain},
      'hourly':hourly}

def main():
    unique={}
    for name,(code,tz) in CITIES.items(): unique.setdefault((code,tz),[]).append(name)
    locations={}; errors={}
    def load(item):
        (code,tz),names=item
        try:
            _,value=city(names[0],code,tz)
            for name in names: locations[name]={**value,'display_name':name}
        except Exception as exc:
            for name in names: errors[name]=type(exc).__name__
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(load,unique.items()))
    old={}
    if DATA.exists():
        try: old=json.loads(DATA.read_text('utf-8')).get('locations',{})
        except Exception: pass
    for name in errors:
        if name in old: locations[name]=old[name]
    out={'updated_at':datetime.now(ZoneInfo('Europe/Moscow')).isoformat(timespec='seconds'),
      'source':{'name':'中国天气网 · China Weather','url':'https://www.weather.com.cn/','operator':'Китайское метеорологическое управление'},
      'locations':locations,'errors':errors}
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')

if __name__=='__main__': main()
