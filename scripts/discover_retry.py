import json,time,sys,os,pandas as pd
import nba_api.stats.endpoints as E
import nba_api.live.nba.endpoints as L
S='2025-26'; g='0022500600'; DEN=1610612743
OUT=sys.argv[1]; os.makedirs(f'{OUT}/frames',exist_ok=True)   # usage: python discover_retry.py <outdir>
out=open(f'{OUT}/results_retry.jsonl','w')
def t(i,fn):
    r={'id':i,'ok':False}; t0=time.time()
    for a in range(3):
        try:
            x=fn()
            if isinstance(x,dict): # live
                r['live_keys']={k:(list(v.keys()) if isinstance(v,dict) else type(v).__name__) for k,v in x.items()}
                r['sample']=json.dumps(x)[:1500]; r['ok']=True; r['nonempty']=True
            else:
                dfs=x.get_data_frames(); names=list(x.expected_data.keys()) if len(x.expected_data)==len(dfs) else [f'set{j}' for j in range(len(dfs))]
                r['sets']={n:{'rows':len(d),'columns':[str(c) for c in d.columns]} for n,d in zip(names,dfs)}
                for n,d in zip(names,dfs):
                    if len(d): d.to_csv(f'{OUT}/frames/{i}__{n}.csv',index=False)
                r['ok']=True; r['nonempty']=any(len(d) for d in dfs)
            break
        except Exception as e:
            r['error']=f'{type(e).__name__}: {str(e)[:200]}'; time.sleep(5)
    r['elapsed_s']=round(time.time()-t0,1); out.write(json.dumps(r)+'\n'); out.flush(); print(i,r['ok'],r.get('error',''),flush=True)
for m in ['Base','Advanced','Four Factors','Misc','Scoring','Opponent','Defense']:
    t(f'TeamGameLogs_{m}',lambda: E.TeamGameLogs(season_nullable=S,measure_type_player_game_logs_nullable=m,timeout=60))
for m in ['Four Factors','Defense']:
    t(f'PlayerGameLogs_{m}',lambda: E.PlayerGameLogs(season_nullable=S,measure_type_player_game_logs_nullable=m,timeout=60))
t('LeagueDashPlayerStats_FourFactors',lambda: E.LeagueDashPlayerStats(season=S,measure_type_detailed_defense='Four Factors',per_mode_detailed='Totals',timeout=60))
t('DefenseHub',lambda: E.DefenseHub(season=S,timeout=60))
t('TeamDashPtShots',lambda: E.TeamDashPtShots(team_id=DEN,season=S,timeout=60))
t('WinProbabilityPBP',lambda: E.WinProbabilityPBP(game_id=g,timeout=60))
t('GameRotation',lambda: E.GameRotation(game_id=g,timeout=60))
t('PlayByPlayV2',lambda: E.PlayByPlayV2(game_id=g,timeout=60))
t('BoxScoreAdvancedV2',lambda: E.BoxScoreAdvancedV2(game_id=g,timeout=60))
t('BoxScoreTraditionalV2',lambda: E.BoxScoreTraditionalV2(game_id=g,timeout=60))
t('live_ScoreBoard',lambda: L.ScoreBoard(timeout=30).get_dict())
t('live_Odds',lambda: L.Odds(timeout=30).get_dict())
t('PlayerNextNGames_2024-25',lambda: E.PlayerNextNGames(player_id=203999,season_all='2024-25',number_of_games=5,timeout=60))
t('ScoreboardV3_20260412',lambda: E.ScoreboardV3(game_date='2026-04-12',timeout=60))
t('ScoreboardV2_20260412',lambda: E.ScoreboardV2(game_date='2026-04-12',timeout=60))
