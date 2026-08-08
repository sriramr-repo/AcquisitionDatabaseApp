#!/usr/bin/env python3
"""
Schema discovery for SEC Form ADV Part 1A dataset.
Classifies columns, identifies candidate entities, and generates mapping.
"""

import duckdb
import re
from collections import defaultdict
from pathlib import Path
import json
from typing import Dict, List, Tuple, Any

def get_connection():
    return duckdb.connect(str(Path("data/analytics.duckdb")))

def classify_column(col_name: str) -> str:
    patterns = [
        (r'^Organization CRD#|SEC#|CIK#|Additional CRD Number|Primary Business Name|Legal Name', 'firm_ident'),
        (r'^Main Office|Mail Office|Location of Books and Records|Office Street Address|Office City|Office State|Office Country|Office Postal Code|Private Residence Flag|Telephone|Facsimile', 'office'),
        (r'^SEC Current Status|SEC Status Effective Date|Jurisdiction Notice Filed-Effective Date|Latest ADV Filing Date|Form Version', 'registration'),
        (r'^Firm Type|Umbrella Registration|Total number of relying advisers|Total number of additional CRD numbers|Total number of CIK numbers|Total Number of Website Addresses|Total Number of Books and Records Locations', 'firm_metadata'),
        (r'^1I|1L|1M|1N|1O|1P', 'form_section_1'),
        (r'^2A\(|3A|3B|3C-|4A|4B', 'form_section_2_3_4'),
        (r'^5A|5B|5C|5D|5E|5F|5G|5H|5I|5J|5K|5L', 'business_activities'),
        (r'^6A|6B', 'fees'),
        (r'^7A|7B', 'affiliates_private_funds'),
        (r'^8A|8B|8C|8D|8E|8F|8G|8H|8I', 'participation_transactions'),
        (r'^9A|9B|9C|9D|9E|9F', 'custody_audit'),
        (r'^10A|Control person|Under Common Control|Share Supervised Persons|Share Location', 'control_persons'),
        (r'^11A|11B|11C|11D|11E|11F|11G|11H|Count of .* disclosures', 'disclosures'),
        (r'^12A|12B|12C', 'misc'),
        (r'^Total number of |Count of |Total |Any |Total Gross Assets', 'aggregates'),
        (r'^SEC Region|Website Address|Acquired Firm|Form Version', 'misc'),
    ]
    for pattern, category in patterns:
        if re.search(pattern, col_name):
            return category
    return 'unclassified'

def analyze_table(table_name: str) -> Dict[str, Any]:
    conn = get_connection()
    # Get column list
    cols = conn.execute(f'DESCRIBE "{table_name}"').fetchall()
    column_details = []
    categories = defaultdict(list)
    
    for row in cols:
        col_name, col_type = row[0], row[1]  # DESCRIBE returns 6 columns
        category = classify_column(col_name)
        column_details.append({
            'name': col_name,
            'type': col_type,
            'category': category
        })
        categories[category].append(col_name)
    
    # Sample distinct values for key columns
    sample_data = {}
    for key_col in ['Organization CRD#', 'SEC#', 'Primary Business Name', 'SEC Current Status']:
        try:
            sample = conn.execute(f'SELECT DISTINCT "{key_col}" FROM "{table_name}" LIMIT 5').fetchall()
            sample_data[key_col] = [s[0] for s in sample]
        except Exception as e:
            sample_data[key_col] = str(e)
    
    # Check for duplicates on CRD#
    dup_check = conn.execute(f'SELECT COUNT(*) as total, COUNT(DISTINCT "Organization CRD#") as distinct_crd FROM "{table_name}"').fetchone()
    total_rows = dup_check[0]
    distinct_crd = dup_check[1]
    
    # Null counts for potential primary key
    null_crd = conn.execute(f'SELECT COUNT(*) FROM "{table_name}" WHERE "Organization CRD#" IS NULL OR TRIM("Organization CRD#") = \'\'').fetchone()[0]
    
    conn.close()
    
    return {
        'table_name': table_name,
        'total_rows': total_rows,
        'distinct_crd': distinct_crd,
        'null_crd_count': null_crd,
        'column_count': len(cols),
        'categories': dict(categories),
        'column_details': column_details,
        'sample_values': sample_data
    }

def suggest_entities(categories: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """Suggest canonical entities based on column categories."""
    suggestions = []
    
    # Firm
    if 'firm_ident' in categories or 'firm_metadata' in categories:
        suggestions.append({
            'entity': 'Firm',
            'description': 'Registered Investment Adviser firm',
            'attributes': categories.get('firm_ident', []) + categories.get('firm_metadata', []),
            'primary_key_candidate': 'Organization CRD#',
            'foreign_keys': []
        })
    
    # Office
    if 'office' in categories:
        suggestions.append({
            'entity': 'Office',
            'description': 'Physical or mailing offices of the firm',
            'attributes': categories['office'],
            'primary_key_candidate': None,
            'foreign_keys': ['Organization CRD#']
        })
    
    # Registration
    if 'registration' in categories:
        suggestions.append({
            'entity': 'Registration',
            'description': 'SEC registration status and filing timeline',
            'attributes': categories['registration'],
            'primary_key_candidate': None,
            'foreign_keys': ['Organization CRD#']
        })
    
    # BusinessActivity
    if 'business_activities' in categories:
        suggestions.append({
            'entity': 'BusinessActivity',
            'description': 'Types of advisory services, client composition, assets under management',
            'attributes': categories['business_activities'],
            'primary_key_candidate': None,
            'foreign_keys': ['Organization CRD#']
        })
    
    # PrivateFund
    if 'affiliates_private_funds' in categories:
        suggestions.append({
            'entity': 'PrivateFund',
            'description': 'Private fund information (hedge, PE, real estate, etc.)',
            'attributes': [c for c in categories['affiliates_private_funds'] if 'Total number of' not in c and 'Any ' not in c],
            'primary_key_candidate': None,
            'foreign_keys': ['Organization CRD#']
        })
    
    # Disclosure
    if 'disclosures' in categories:
        suggestions.append({
            'entity': 'Disclosure',
            'description': 'Regulatory disclosures (disciplinary events, financial, etc.)',
            'attributes': [c for c in categories['disclosures'] if not c.startswith('Count of ')],
            'primary_key_candidate': None,
            'foreign_keys': ['Organization CRD#']
        })
    
    # ControlPerson
    if 'control_persons' in categories:
        suggestions.append({
            'entity': 'ControlPerson',
            'description': 'Persons controlling the advisory firm',
            'attributes': categories['control_persons'],
            'primary_key_candidate': None,
            'foreign_keys': ['Organization CRD#']
        })
    
    return suggestions

def main():
    table_name = 'bronze_raw_IA_SEC___FIRM_ROSTER_FOIA_DOWNLOAD___34622660_ia07012026'
    print(f'Analyzing table: {table_name}')
    analysis = analyze_table(table_name)
    
    print(f'Total rows: {analysis["total_rows"]}')
    print(f'Distinct CRD#: {analysis["distinct_crd"]}')
    print(f'Null CRD# count: {analysis["null_crd_count"]}')
    print(f'Column count: {analysis["column_count"]}')
    
    print('\n--- Column Categories ---')
    for cat, cols in analysis['categories'].items():
        print(f'{cat}: {len(cols)} columns')
    
    print('\n--- Sample Values ---')
    for key, values in analysis['sample_values'].items():
        print(f'{key}: {values}')
    
    # Entity suggestions
    suggestions = suggest_entities(analysis['categories'])
    print('\n--- Suggested Canonical Entities ---')
    for s in suggestions:
        print(f'Entity: {s["entity"]}')
        print(f'  Description: {s["description"]}')
        print(f'  Attributes: {len(s["attributes"])}')
        if s['primary_key_candidate']:
            print(f'  Primary Key Candidate: {s["primary_key_candidate"]}')
        if s['foreign_keys']:
            print(f'  Foreign Keys: {s["foreign_keys"]}')
        print()
    
    # Write detailed report
    report_path = Path('data/schema_discovery_report.json')
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump({
            'analysis': analysis,
            'suggested_entities': suggestions
        }, f, indent=2)
    print(f'Detailed report written to {report_path}')

if __name__ == '__main__':
    main()