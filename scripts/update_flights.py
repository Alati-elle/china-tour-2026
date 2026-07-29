#!/usr/bin/env python3
import json, re, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'/'flights.json'
CS='https://m.csair.com/CSMBP/microFlight/flightstatus/getstatusnew.do?type=MOBILE&APPTYPE=touch&chanel=touch&lang=en&holder=TOUCH'
STATUS={'SCH':'По расписанию','DLY':'Задержан','BDSTR':'Идёт посадка','BDQCK':'Последний вызов','CLSDR':'Выход закрыт','BDEND':'Посадка завершена','OFF':'Руление','AIR':'Вылетел','DWN':'Приземлился','ONN':'Прибыл','CNL':'Отменён','DVT':'Меняет маршрут','DVTO':'Направлен в другой аэропорт','RTN':'Возвращается'}

def airline(number,date):
    body=json.dumps({'type':4,'date':date.replace('-',''),'flight':number.removeprefix('CZ').zfill(4)}).encode()
    req=urllib.request.Request(CS,data=body,headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'Mozilla/5.0','Referer':'https://m.csair.com/flightstatus_new/'})
    raw=urllib.request.urlopen(req,timeout=35).read().decode('utf-8','replace')
    data=json.loads(raw); text=json.dumps(data,ensure_ascii=False)
    code=next((c for c in STATUS if ('"'+c+'"') in text),None)
    times=re.findall(r'(?<!\d)([012]\d:[0-5]\d)(?!\d)',text)
    return (STATUS.get(code,'Статус ещё не опубликован')+((' · '+times[0]) if code and times else ''))

def main():
    data=json.loads(DATA.read_text('utf-8'))
    for number,flight in data['flights'].items():
        try: flight['sources'][0]['status']=airline(number,flight['date'])
        except Exception as exc: flight['sources'][0]['error']=type(exc).__name__
    data['updated_at']=datetime.now(ZoneInfo('Europe/Moscow')).isoformat(timespec='seconds')
    DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n','utf-8')
if __name__=='__main__': main()
