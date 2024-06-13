This is an attempt at a disciplined benchmark for coverage performance.  The
goal is to run real-world test suites under controlled conditions to measure
relative performance.

We want to be able to make comparisons like:

- Is coverage under Python 3.12 faster than under 3.11?

- What is the performance overhead of coverage measurement compared to no
  coverage?

- How does sys.monitoring overhead compare to sys.settrace overhead?


Challenges:

- Real-world test suites have differing needs and differing styles of
  execution. It's hard to invoke them uniformly and get consistent execution.

- The projects might not yet run correctly on the newer versions of Python that
  we want to test.

- Projects don't have uniform ways of setting coverage options.  For example,
  we'd like to be able to run the test suite both with and without coverage
  measurement, but many projects aren't configured to make that possible.


Running
-------

The benchmark.py module defines the ``run_experiment`` function and helpers to
build its arguments.

If you create compare-10-11.py like this::

    # Compare two Python versions
    run_experiment(
        py_versions=[
            Python(3, 10),
            Python(3, 11),
        ],
        cov_versions=[
            Coverage("753", "coverage==7.5.3"),
        ],
        projects=[
            ProjectMashumaro(),
            ProjectOperator(),
        ],
        rows=["cov", "proj"],
        column="pyver",
        ratios=[
            ("3.11 vs 3.10", "python3.11", "python3.10"),
        ],
        num_runs=1,
    )

This produces this output::

    % python compare-10-11.py
    Removing and re-making /tmp/covperf
    Logging output to /private/tmp/covperf/output_mashumaro.log
    Prepping project mashumaro
    Making venv for mashumaro python3.10
    Prepping for mashumaro python3.10
    Making venv for mashumaro python3.11
    Prepping for mashumaro python3.11
    Logging output to /private/tmp/covperf/output_operator.log
    Prepping project operator
    Making venv for operator python3.10
    Prepping for operator python3.10
    Making venv for operator python3.11
    Prepping for operator python3.11
    Logging output to /private/tmp/covperf/output_mashumaro.log
    Running tests: proj=mashumaro, py=python3.11, cov=753, 1 of 4
    Results: TOTAL                                                                     11061     66  99.403309%
    Tests took 75.985s
    Logging output to /private/tmp/covperf/output_operator.log
    Running tests: proj=operator, py=python3.11, cov=753, 2 of 4
    Results: TOTAL                       6021    482  91.994685%
    Tests took 94.856s
    Logging output to /private/tmp/covperf/output_mashumaro.log
    Running tests: proj=mashumaro, py=python3.10, cov=753, 3 of 4
    Results: TOTAL                                                                     11061    104  99.059760%
    Tests took 77.815s
    Logging output to /private/tmp/covperf/output_operator.log
    Running tests: proj=operator, py=python3.10, cov=753, 4 of 4
    Results: TOTAL                       6021    482  91.994685%
    Tests took 108.106s
    # Results
    Median for mashumaro, python3.10, 753: 77.815s, stdev=0.000, data=77.815
    Median for mashumaro, python3.11, 753: 75.985s, stdev=0.000, data=75.985
    Median for operator, python3.10, 753: 108.106s, stdev=0.000, data=108.106
    Median for operator, python3.11, 753: 94.856s, stdev=0.000, data=94.856

    | cov   | proj      |   python3.10 |   python3.11 |   3.11 vs 3.10 |
    |:------|:----------|-------------:|-------------:|---------------:|
    | 753   | mashumaro |        77.8s |        76.0s |            98% |
    | 753   | operator  |       108.1s |        94.9s |            88% |
