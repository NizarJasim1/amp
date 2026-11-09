PY ?= python3

.PHONY: kit test mock clean

kit:
	$(PY) src/make_kit.py --seeds 30 --out kit

test: kit
	cd tests_code && $(PY) -m unittest discover -p 'test_*.py'

mock: kit
	$(PY) runner/amp_runner.py --kit kit --runs runs_mock --config runner/providers.mock.json --limit 3
	$(PY) kit/grader/grade.py runs_mock kit

clean:
	rm -rf runs_mock _work
	find . -name __pycache__ -prune -exec rm -rf {} +
