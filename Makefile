# PtD 라이브러리 v2.4 파이프라인
#
# 이 환경에는 make 와 Node.js 가 없다. 동일 순서를 실행하는 실행기가 있다:
#     python scripts/build_all.py
# make 가 있는 환경에서는 아래 타깃이 그대로 동작한다 (순서 동일).
#
# 순서: migrate → clean → adjudicate → kalis → ttl → validate → docx

PYTHON ?= python
S      := scripts

.PHONY: all migrate clean_directives adjudicate kalis ttl validate docx clean

all: migrate clean_directives adjudicate kalis ttl validate docx

migrate:
	$(PYTHON) $(S)/migrate.py

clean_directives: migrate
	$(PYTHON) $(S)/clean_directives.py

adjudicate: clean_directives
	$(PYTHON) $(S)/adjudicate.py

kalis:
	$(PYTHON) $(S)/kalis_unadopted.py

ttl: adjudicate
	$(PYTHON) $(S)/build_ttl.py

validate: ttl
	$(PYTHON) $(S)/validate.py

docx: adjudicate kalis ttl
	$(PYTHON) $(S)/build_docx.py

clean:
	rm -f build/ptd_library_master_v2.4.csv build/ptd_library_v2.4.ttl \
	      build/Appendix_PtD_Library_v2.4.docx build/adjudication_report.md \
	      build/kalis_unadopted_summary.csv build/validate_report.txt \
	      build/migrate_log.txt build/directive_cleanup_log.md
