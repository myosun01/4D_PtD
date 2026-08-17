#!/usr/bin/env python3
"""ptd_library_master_v1.xlsx → ptd_library_v2.ttl 생성기.
마스터 표가 단일 원천(SSoT). TTL은 항상 이 스크립트로 재생성하고 직접 수정하지 않는다.
사용법: python3 build_ttl_from_master.py [master.xlsx] [out.ttl]"""
import sys, pandas as pd

MASTER = sys.argv[1] if len(sys.argv)>1 else 'ptd_library_master_v1.xlsx'
OUT    = sys.argv[2] if len(sys.argv)>2 else 'ptd_library_v2.ttl'
S = pd.read_excel(MASTER, sheet_name=None)
E = lambda s: str(s).replace('\\','').replace('"',"'").replace('\n',' ').strip()
MV = lambda s: [x.strip() for x in str(s).split(';') if x.strip() and x.strip()!='nan']
NN = lambda v: v is not None and str(v)!='nan' and str(v).strip()!=''

HEADER = '''# 자동 생성 파일 — 수정 금지. 원천: ptd_library_master_v1.xlsx (build_ttl_from_master.py)
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix ptd:  <http://construction-safety.org/ptd-hoc-ontology#> .
<http://construction-safety.org/ptd-hoc-ontology> a owl:Ontology ;
    owl:versionInfo "2.2-generated" ;
    rdfs:comment "RC 골조 4D PtD 실행 가능 지식 라이브러리 — 마스터 표에서 생성"@ko .
'''
CLASSES = ['HazardType','HoCLevel','PtDAlternative','SimulationRule','Reference','KnowledgeEntry',
 'RiskScenario','CoverageCell','AccidentType','Trade','LifecycleRuleTemplate','ConflictResolution']
SUB = {'SpatialChangeRule':'SimulationRule','AgentParameterRule':'SimulationRule',
 'TemporalRule':'SimulationRule','ExecutableAlternative':'PtDAlternative'}
HOC = ['RiskAvoidance','Elimination','Substitution','EngineeringControls','WarningSystems','AdministrativeControls','PPE']
PARAM_DT = {'fallProbMultiplier':'decimal','hazardWeightMultiplier':'decimal','riskCoefficientMultiplier':'decimal',
 'fatalityMultiplier':'decimal','injuryMultiplier':'decimal','equipProbMultiplier':'decimal','routePenaltyMultiplier':'decimal',
 'collapseProbMultiplier':'decimal','materialProbMultiplier':'decimal','tripProbMultiplier':'decimal'}

L=[HEADER]
L += [f'ptd:{c} a owl:Class .' for c in CLASSES]
L += [f'ptd:{c} a owl:Class ; rdfs:subClassOf ptd:{p} .' for c,p in SUB.items()]
L.append('ptd:isHigherThan a owl:ObjectProperty , owl:TransitiveProperty .')
for i,h in enumerate(HOC):
    nxt = f' ; ptd:isHigherThan ptd:{HOC[i+1]}' if i+1<len(HOC) else ''
    L.append(f'ptd:{h} a ptd:HoCLevel{nxt} .')

def emit(subj, cls, pairs):
    body = ' ;\n    '.join(f'{p} {v}' for p,v in pairs if v)
    L.append(f'ptd:{subj} a ptd:{cls} ;\n    {body} .' if body else f'ptd:{subj} a ptd:{cls} .')
lit  = lambda s: f'"{E(s)}"@ko'
lite = lambda s: f'"{E(s)}"'
refs = lambda s: ', '.join(f'ptd:{r}' for r in MV(s))

for _,r in S['J_References'].iterrows():
    emit(r.RefID,'Reference',[('ptd:sourceDocument',lite(r.Citation)),
        ('ptd:evidenceLevel',lite(r.EvidenceLevel) if NN(r.EvidenceLevel) else ''),
        ('rdfs:comment',lit(r.Comment) if NN(r.Comment) else '')])
for _,r in S['F_AccidentTypes'].iterrows():
    emit(r.ID,'AccidentType',[('rdfs:label',lit(r.Label)),
        ('ptd:fatalityShare',str(r.FatalityShare) if NN(r.FatalityShare) else ''),
        ('ptd:frequencyShare',str(r.FrequencyShare) if NN(r.FrequencyShare) else ''),
        ('ptd:rcFatalCount',str(int(r.RC_FatalCount)) if NN(r.RC_FatalCount) else ''),
        ('ptd:hasReference',refs(r.References)),
        ('rdfs:comment',lit(r.Comment) if NN(r.Comment) else '')])
for _,r in S['G_Trades'].iterrows():
    emit(r.ID,'Trade',[('rdfs:label',lit(r.Label)),('ptd:hasReference',refs(r.References) if NN(r.References) and 'REF' in str(r.References) else '')])
for _,r in S['H_HazardTypes'].iterrows():
    if str(r.DeclaredIn).startswith('v1'): continue
    emit(r.ID,'HazardType',[('rdfs:label',lit(r.Label)),
        ('ptd:simulationProfile',lite(r.SimProfile) if NN(r.SimProfile) else ''),
        ('ptd:applicableInCurrentSimulator',f'"{str(r.ApplicableNow).lower()}"^^xsd:boolean' if NN(r.ApplicableNow) else ''),
        ('ptd:hasReference',refs(r.References)),('rdfs:comment',lit(r.Comment) if NN(r.Comment) else '')])
cells = set(S['E_CoverageCells'].ID)
for _,r in S['E_CoverageCells'].iterrows():
    emit(r.ID,'CoverageCell',[('ptd:hasAccidentType',f'ptd:{r.AccidentType}' if NN(r.AccidentType) else ''),
        ('ptd:hasTrade',f'ptd:{r.Trade}' if NN(r.Trade) else ''),
        ('ptd:priorityClass',lite(r.Priority) if NN(r.Priority) else ''),
        ('ptd:targetKnowledgeEntries',str(int(r.TargetKE)) if NN(r.TargetKE) else ''),
        ('ptd:targetExecutableAlts',str(int(r.TargetEA)) if NN(r.TargetEA) else ''),
        ('ptd:hasReference',refs(r.References))])
ACC_OF={'Fall':'ACC_Fall','Trip':'ACC_Trip','HitByObj':'ACC_HitByObj','Caught':'ACC_Caught','Struck':'ACC_Struck','Collapse':'ACC_Collapse'}
TRD_OF={'Rebar':'TRD_Rebar','FormErection':'TRD_FormworkErection','Pour':'TRD_ConcretePour','Stripping':'TRD_FormworkStripping','MatHandling':'TRD_MaterialHandling'}
for _,r in S['D_RiskScenarios'].iterrows():
    cid=f"CELL_{r.Cell}"
    if NN(r.Cell) and cid not in cells:   # 시나리오가 참조하는 미선언 셀 자동 스텁
        a,t=str(r.Cell).split('_',1)
        emit(cid,'CoverageCell',[('ptd:hasAccidentType',f'ptd:{ACC_OF.get(a,"")}'),
            ('ptd:hasTrade',f'ptd:{TRD_OF.get(t,"")}'),('ptd:priorityClass','"P2"'),
            ('rdfs:comment',lit('시나리오 참조로 자동 선언된 스텁 셀'))])
        cells.add(cid)
    emit(r.ID.replace('-','_'),'RiskScenario',[('rdfs:label',lit(r.Label)),
        ('ptd:belongsToCell',f'ptd:{cid}' if NN(r.Cell) else ''),
        ('ptd:hasHazardType',', '.join(f'ptd:{h}' for h in MV(r.HazardTypes))),
        ('ptd:hasReference',refs(r.References)),('ptd:collectionStatus',lite(r.Status))])
for _,r in S['I_LifecycleRules'].iterrows():
    emit(r.ID,'LifecycleRuleTemplate',[('ptd:spawnTrigger',lite(r.SpawnTrigger)),
        ('ptd:despawnTrigger',lite(r.DespawnTrigger)),('ptd:locationSelector',lite(r.LocationSelector)),
        ('ptd:hasHazardType',f'ptd:{r.HazardType}' if NN(r.HazardType) else ''),('ptd:hasReference',refs(r.References))])
for _,r in S['B_KnowledgeEntries'].iterrows():
    emit(r.ID,'KnowledgeEntry',[('ptd:alternativeDescription',lit(r.Description)),
        ('ptd:hasHoCLevel',f'ptd:{r.HoC}'),
        ('ptd:isDesignDecidable',str(r.DesignDecidable).lower() if NN(r.DesignDecidable) else ''),
        ('ptd:designDecisionType',lite(r.DecisionType) if NN(r.DecisionType) else ''),
        ('ptd:belongsToCell',', '.join(f'ptd:{c}' for c in MV(r.BelongsToCell))),
        ('ptd:addressesScenario',', '.join(f'ptd:{s}' for s in MV(r.AddressesScenarios))),
        ('ptd:caseCount',str(int(float(r.CaseCount))) if NN(r.CaseCount) else ''),
        ('ptd:hasReference',refs(r.References)),
        ('ptd:sourceSection',lite(r.SourceSection) if NN(r.SourceSection) else ''),
        ('ptd:evidenceLevel',lite(r.EvidenceLevel) if NN(r.EvidenceLevel) else ''),
        ('ptd:collectionStatus',lite(r.Status) if NN(r.Status) else ''),
        ('ptd:promotedTo',f'ptd:{r.PromotedTo}' if NN(r.PromotedTo) else ''),
        ('ptd:promotionStatus',lite(r.PromotionStatus) if NN(r.PromotionStatus) else ''),
        ('ptd:promotionNote',lit(r.PromotionNote) if NN(r.PromotionNote) else ''),
        ('rdfs:comment',lit(r.Comment) if NN(r.Comment) else '')])
for _,r in S['C_ExecutableAlternatives'].iterrows():
    emit(r.AltID,'ExecutableAlternative',[('ptd:alternativeID',lite(r.AltID)),
        ('ptd:fromEntry',f'ptd:{r.FromEntry}'),('ptd:hasHoCLevel',f'ptd:{r.HoC}'),
        ('ptd:hasSimulationRule',f'ptd:{r.RuleID}'),
        ('ptd:installCostLevel',lite(r.InstallCost) if NN(r.InstallCost) else ''),
        ('ptd:installDurationDays',str(int(float(r.InstallDays))) if NN(r.InstallDays) else '')])
    pairs=[('ptd:scheduleShift' if r.RuleType=='TemporalRule' else 'ptd:simulationAction',lite(r.Action) if NN(r.Action) else '')]
    pairs+=[('ptd:appliesToCellType',lite(r.AppliesToCellType) if NN(r.AppliesToCellType) else ''),
        ('ptd:applicabilityCondition',lite(r.ApplicabilityCondition) if NN(r.ApplicabilityCondition) else '')]
    for pv in MV(r.Parameters):
        k,v=pv.split('='); pairs.append((f'ptd:{k}',f'"{v}"^^xsd:{PARAM_DT[k]}'))
    pairs+=[('ptd:parameterSourceType',lite(r.ParamSource) if NN(r.ParamSource) else ''),
        ('ptd:evidenceLevel',lite(r.EvidenceLevel) if NN(r.EvidenceLevel) else ''),
        ('ptd:sensitivityTarget','true' if str(r.SensitivityTarget).lower()=='true' else ''),
        ('ptd:parameterJustification',lit(r.Justification) if NN(r.Justification) else ''),
        ('ptd:hasReference',refs(r.RuleReferences))]
    emit(r.RuleID,r.RuleType,pairs)
for _,r in S['K_ConflictResolutions'].iterrows():
    emit(r.ID,'ConflictResolution',[('rdfs:comment',lit(r.Resolution))])

open(OUT,'w').write('\n'.join(L)+'\n')
print(f'{OUT} 생성 완료 ({len(L)} 블록)')
