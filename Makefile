
clean:
	- find ./test -name "*.csv" -type f | xargs rm
	rm -rf out

test:
	. ./venv/bin/activate && echo test/*py | xargs -n 1 python3

.PHONY: test
