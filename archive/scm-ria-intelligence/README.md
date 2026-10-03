# SCM RIA Acquisition Intelligence Platform

## Overview
The SCM RIA Acquisition Intelligence Platform is a Python-based data intelligence platform designed to identify Registered Investment Advisers (RIAs) that may be acquisition, merger, succession, employment, strategic partnership, or sub-advisory opportunities for Standish Capital Management.

## Project Goals
- Download and process SEC Form ADV bulk datasets
- Normalize multiple datasets into a unified schema
- Store normalized records in a research database
- Score RIAs based on acquisition criteria
- Export actionable intelligence in Excel reports
- Generate candidate lists for acquisition opportunities
- Support manual research and data exploration
- Maintain historical snapshots for trend analysis
- Support quarterly data updates

## Architecture
```
scm-ria-intelligence/
├── data/                    # Data storage directories
│   ├── raw/                # Raw downloaded datasets
│   ├── processed/          # Cleaned and normalized data
│   ├── exports/            # Generated reports and exports
│   └── database/           # SQLite database files
├── src/                    # Source code
│   ├── ingest/            # Data ingestion modules
│   ├── cleaning/          # Data cleaning and normalization
│   ├── models/            # Data models and schemas
│   ├── scoring/           # RIA scoring algorithms
│   ├── reports/           # Report generation
│   ├── research/          # Manual research tools
│   └── utils/             # Shared utilities
├── tests/                  # Test suites
│   ├── unit/              # Unit tests
│   └── integration/       # Integration tests
├── docs/                   # Documentation
├── config/                 # Configuration files
├── scripts/                # Utility scripts
└── notebooks/             # Jupyter notebooks for analysis
```

## Tech Stack
- Python 3.12+
- SQLite for local database
- Pandas for data manipulation
- NumPy for numerical operations
- OpenPyXL for Excel reporting
- Requests for HTTP operations
- BeautifulSoup & Playwright (future)
- Typer for CLI interface
- Pytest for testing
- Black & Ruff for code quality
- python-dotenv for configuration

## Getting Started

### Prerequisites
- Python 3.12 or higher
- Git

### Installation
1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy environment variables:
   ```bash
   cp .env.example .env
   ```
5. Configure your `.env` file with appropriate settings

## Development

### Code Quality
- Follow PEP 8 guidelines
- Use type hints for all functions
- Write comprehensive docstrings
- Run code quality tools:
  ```bash
  black src/
  ruff check src/
  ```

### Testing
```bash
pytest tests/ -v
```

### CLI Usage
```bash
# Download SEC Form ADV data
python -m src.cli download-data

# Clean and normalize data
python -m src.cli clean-data

# Build database
python -m src.cli build-database

# Score firms
python -m src.cli score-firms

# Generate reports
python -m src.cli generate-report

# Launch research interface
python -m src.cli research

# Refresh all data
python -m src.cli refresh
```

## Future Roadmap
### Phase 1: Foundation (Current)
- Project architecture setup
- Database connection layer
- Configuration management
- CLI framework
- Testing infrastructure

### Phase 2: Data Ingestion
- SEC Form ADV data download
- Data parsing and extraction
- Bulk dataset processing

### Phase 3: Data Processing
- Data cleaning pipelines
- Schema normalization
- Database schema design
- Data validation

### Phase 4: Scoring Engine
- Acquisition scoring algorithms
- Opportunity identification
- Risk assessment models

### Phase 5: Reporting
- Excel report generation
- Custom report templates
- Data visualization

### Phase 6: Research Tools
- Interactive research interface
- Manual data entry
- Candidate tracking

## Contributing
1. Create a feature branch
2. Make your changes
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License
Proprietary - Standish Capital Management