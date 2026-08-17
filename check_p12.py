from schedule import Schedule
from lifecycle import LifecycleEngine
import ptd_ttl

s = Schedule.load('project/schedule.json')
e = LifecycleEngine(ptd_ttl.LIBRARY.lifecycle_templates,
                    'project/lifecycle_bindings.json', s)
print('공기(작업일):', s.duration)                 # 409
print('위험 인스턴스:', len(e.instances))            # 21
print('H008 층(직하부):', [h.level for h in e.instances
                          if h.hazard_type == 'H008'][:3])   # ['L1','L2','L3']