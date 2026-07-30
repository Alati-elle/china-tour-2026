#!/usr/bin/env python3
import gzip, json, urllib.parse, urllib.request, uuid, subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'flights.json'
CS='https://m.csair.com/CSMBP/microFlight/flightstatus/getstatusnew.do?type=MOBILE&APPTYPE=touch&chanel=touch&lang=en&holder=TOUCH'
SVO='https://www.svo.aero/bitrix/timetable/'
PKX='https://wechat.bdia.com.cn/service/flt/getByFltNo'
CS_STATUS={'SCH':'По расписанию','DLY':'Задержан','BDSTR':'Идёт посадка','BDQCK':'Последний вызов','CLSDR':'Выход закрыт','BDEND':'Посадка завершена','OFF':'Руление','AIR':'Вылетел','DWN':'Приземлился','ONN':'Прибыл','CNL':'Отменён','DVT':'Меняет маршрут','DVTO':'Направлен в другой аэропорт','RTN':'Возвращается'}

def request_json(url, body=None):
    cmd=["curl","--compressed","-fsSL","--max-time","20","-A","Mozilla/5.0","-H","Accept: application/json"]
    if body is not None: cmd += ["-H","Content-Type: application/json","-d",json.dumps(body)]
    raw=subprocess.run(cmd+[url],capture_output=True,check=True,timeout=25).stdout
    return json.loads(raw.decode("utf-8","replace"))

def fmt_time(value):
    return value[11:16] if value and len(value)>=16 else ''

def airline(number,date):
    payload={'type':4,'date':date.replace('-',''),'flight':number.removeprefix('CZ').zfill(4)}
    data=request_json(CS,payload)
    row=(data.get('flights') or [None])[0]
    if not row: return None
    code=row.get('fltCode','')
    status=CS_STATUS.get(code,row.get('fltSts') or 'Статус ещё не опубликован')
    time=fmt_time(row.get('latestDepDt') or row.get('actDepDt') or row.get('schDepDt'))
    return {'status':status+((' · '+time) if time else ''),'row':row}

def svo_flight(number,date):
    start=date+'T00:00:00+03:00'
    end=(datetime.fromisoformat(date)+timedelta(days=1)).date().isoformat()+'T00:00:00+03:00'
    query=urllib.parse.urlencode({'direction':'departure','dateStart':start,'dateEnd':end,'perPage':9999,'page':0,'locale':'ru'})
    items=request_json(SVO+'?'+query).get('items',[])
    carrier=''.join(c for c in number if c.isalpha()); wanted=''.join(c for c in number if c.isdigit()).lstrip('0')
    return next((x for x in items if x.get('co',{}).get('code')==carrier and str(x.get('flt','')).lstrip('0')==wanted),None)

def pkx_flight(number,date):
    session=str(uuid.uuid4())
    query=urllib.parse.urlencode({'language':'CN','source':'SITE','openId':session,'userCode':'','pid':session})
    data=request_json(PKX+'?'+query,{'fltNo':number,'queryDate':date}).get('data') or {}
    rows=data.get('DEP') or []
    return rows[0] if rows else None

def set_source(flight,name,status,url):
    source=next((x for x in flight['sources'] if x['name']==name),None)
    if source: source.update(status=status,url=url)
    else: flight['sources'].append({'name':name,'status':status,'url':url})

def update_airline(number,flight):
    result=airline(number,flight['date'])
    if not result: return
    set_source(flight,'China Southern',result['status'],'https://www.csair.com/en/online/flight_dynamic/')
    row=result['row']; d=flight['details']
    d['terminal']=row.get('depAirportTerminal') or d.get('terminal') or 'Ещё не опубликован'
    d['aircraft']=row.get('acfleet') or d.get('aircraft') or 'Ещё не опубликован'
    d['estimated_departure']=fmt_time(row.get('latestDepDt')) or fmt_time(row.get('schDepDt')) or 'Ещё не опубликовано'
    d['actual_departure']=fmt_time(row.get('actDepDt')) or '—'
    arrived_status=row.get('fltCode') in {'DWN','ONN'}
    actual_arrival=row.get('actArvDt') or (row.get('latestArvDt') if arrived_status else '')
    if actual_arrival:
        arrival_tz=ZoneInfo('Asia/Shanghai' if number=='CZ342' else 'Europe/Moscow')
        arrived=datetime.fromisoformat(actual_arrival)
        if arrived.tzinfo is None: arrived=arrived.replace(tzinfo=arrival_tz)
        flight['actual_arrival_at']=arrived.isoformat(timespec='minutes')
        d['actual_arrival']=fmt_time(actual_arrival)

def update_svo(number,flight):
    row=svo_flight(number,flight['date'])
    if not row: return
    status=row.get('vip_status_rus') or 'Статус ещё не опубликован'
    url=f"https://www.svo.aero/ru/timetable/departure/flight/{row['i_id']}/departing"
    set_source(flight,'Шереметьево',status,url)
    d=flight['details']
    if 'егистрац' in status: checkin=status
    elif row.get('t_chin_finish'): checkin='Завершена'
    else: checkin='Ещё не началась'
    d.update(airport_checkin=checkin,terminal=row.get('term') or 'Ещё не опубликован',
             checkin_counters=row.get('chin_id') or 'Ещё не опубликованы',
             gate=str(row.get('gate_id') or 'Ещё не опубликован'),
             boarding='Идёт' if row.get('t_boarding_start') and not row.get('t_bording_finish') else ('Завершена' if row.get('t_bording_finish') else 'Ещё не началась'),
             estimated_departure=fmt_time(row.get('t_et')) or fmt_time(row.get('t_st')) or 'Ещё не опубликовано',
             actual_departure=fmt_time(row.get('t_otpr')) or '—',
             aircraft=row.get('aircraft_type_name') or 'Ещё не опубликован')

def update_pkx(number,flight):
    row=pkx_flight(number,flight['date'])
    if not row: return
    status=row.get('fltAbnStatusDesc') or row.get('status') or 'Статус ещё не опубликован'
    if row.get('delayDesc'): status+=' · '+row['delayDesc']
    set_source(flight,'Аэропорт Дасин',status,'https://wechat.bdia.com.cn/')
    d=flight['details']
    checkin={'I':'Идёт','E':'Завершена'}.get(row.get('ckiStatus'),'Ещё не началась')
    boarding='Идёт' if row.get('boardingStartTime') and not row.get('depActTime') else ('Завершена' if row.get('depActTime') else 'Ещё не началась')
    d.update(airport_checkin=checkin,terminal=row.get('depTerm') or 'Ещё не опубликован',
             checkin_counters=row.get('counterDisp') or 'Ещё не опубликованы',
             gate=row.get('gateDisp') or 'Ещё не опубликован',boarding=boarding,
             estimated_departure=fmt_time(row.get('depEstTime')) or fmt_time(row.get('depSchTime')) or 'Ещё не опубликовано',
             actual_departure=fmt_time(row.get('depActTime')) or '—',
             aircraft=row.get('planeType') or 'Ещё не опубликован')
    if row.get('delayDesc'): d['delay_reason']=row['delayDesc']

def is_arrived(flight):
    return bool(flight.get('actual_arrival_at'))

def main():
    data=json.loads(DATA.read_text('utf-8')); errors={}; checked=[]
    def process(item):
        number,flight=item
        if flight.get('frozen_at'): return
        if is_arrived(flight):
            flight['frozen_at']=datetime.now(timezone.utc).isoformat(timespec='seconds')
            flight['refresh_stopped']=True
            checked.append(number)
            return
        for label,fn in [('airline',update_airline),('airport',update_svo if number=='CZ342' else update_pkx)]:
            try: fn(number,flight)
            except Exception as exc: errors[number+'_'+label]=type(exc).__name__
        flight['last_checked_at']=datetime.now(timezone.utc).isoformat(timespec='seconds')
        if is_arrived(flight):
            flight['frozen_at']=flight['last_checked_at']
            flight['refresh_stopped']=True
        checked.append(number)
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(process,data['flights'].items()))
    if not checked: return
    data['updated_at']=datetime.now(ZoneInfo('Europe/Moscow')).isoformat(timespec='seconds')
    data['refresh_interval_minutes']=5; data['errors']=errors
    DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n','utf-8')

if __name__=='__main__': main()
