# Contributing to PathSafe

Thanks for your interest in contributing.

## Ground Rules

- Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
- Do not include real patient data, PHI, or confidential information in issues, commits, or tests.
- Keep pull requests focused and easy to review.

## Development Setup

1. Fork and clone the repository.
2. Create a virtual environment.
3. Install development dependencies:

```bash
pip install -e ".[dev,dicom,convert]"
```

4. Run tests:

```bash
pytest tests/ -v --tb=short
```

## Pull Request Process

1. Create a branch from `master`.
2. Make your changes with tests when applicable.
3. Ensure the test suite passes locally.
4. Open a pull request with:
   - what changed
   - why it changed
   - any risks or follow-up work

## Commit Style

- Use clear, descriptive commit messages.
- Keep commits logically grouped.

## Reporting Bugs

Please use the bug report issue template and include:

- what you expected
- what happened
- exact steps to reproduce
- OS and Python version

## Suggesting Features

Please use the feature request issue template and explain:

- problem being solved
- proposed behavior
- alternatives considered

