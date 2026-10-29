import inspect, importlib, pkgutil, json
import nba_api.stats.endpoints as E
import nba_api.live.nba.endpoints as L
out={}
for mod in [E,L]:
    for m in pkgutil.iter_modules(mod.__path__):
        try: M=importlib.import_module(mod.__name__+'.'+m.name)
        except Exception as e: continue
        for n,c in inspect.getmembers(M,inspect.isclass):
            if c.__module__!=M.__name__ or n in('Endpoint',): continue
            try: sig=inspect.signature(c.__init__)
            except: continue
            params={k:(None if v.default is inspect._empty else repr(v.default)) for k,v in sig.parameters.items() if k not in('self','proxy','headers','timeout','get_request')}
            out[n]={'module':mod.__name__.split('.')[-3]+'.'+m.name,'endpoint':getattr(c,'endpoint',None),'params':params,'expected':list(getattr(c,'expected_data',{}).keys()) if hasattr(c,'expected_data') else None}
json.dump(out,open('introspect.json','w'),indent=1)
print(len(out))
for k,v in out.items(): print(k,v['endpoint'],len(v['params']),v['expected'] and len(v['expected']))
