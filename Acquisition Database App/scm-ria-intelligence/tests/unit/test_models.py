"\"\"\"Unit tests for data models and schemas.\"\"\"

import pytest
from datetime import date, datetime

from src.models.schemas import (
    Address,
    Contact,
    RIABasicInfo,
    RIAFinancials,
    RIAServices,
    RIAFees,
    RIAAdvisor,
    RIAFirm,
    AcquisitionScore,
    AcquisitionCandidate,
)


class TestDataModels:
    \"\"\"Test data model classes.\"\"\"
    
    def test_address_model(self):
        \"\"\"Test Address model.\"\"\"
        address = Address(
            street="123 Main St",
            city="Boston",
            state="MA",
            zip_code="02101",
            country="US",
            address_type="business"
        )
        
        assert address.street == "123 Main St"
        assert address.city == "Boston"
        assert address.state == "MA"
        assert address.zip_code == "02101"
        assert address.country == "US"
        assert address.address_type == "business"
        
    def test_contact_model(self):
        \"\"\"Test Contact model.\"\"\"
        contact = Contact(
            name="John Smith",
            title="Chief Investment Officer",
            email="john.smith@example.com",
            phone="617-555-1234",
            phone_extension="123"
        )
        
        assert contact.name == "John Smith"
        assert contact.title == "Chief Investment Officer"
        assert contact.email == "john.smith@example.com"
        assert contact.phone == "617-555-1234"
        assert contact.phone_extension == "123"
        
    def test_ria_basic_info(self):
        \"\"\"Test RIABasicInfo model.\"\"\"
        basic_info = RIABasicInfo(
            crd_number=123456,
            legal_name="Example Wealth Management LLC",
            doing_business_as="Example Wealth",
            sec_file_number="801-12345",
            status="active",
            registration_date=date(2010, 5, 15)
        )
        
        assert basic_info.crd_number == 123456
        assert basic_info.legal_name == "Example Wealth Management LLC"
        assert basic_info.doing_business_as == "Example Wealth"
        assert basic_info.sec_file_number == "801-12345"
        assert basic_info.status == "active"
        assert basic_info.registration_date == date(2010, 5, 15)
        
    def test_ria_financials(self):
        \"\"\"Test RIAFinancials model.\"\"\"
        financials = RIAFinancials(
            crd_number=123456,
            assets_under_management=500000000.0,
            discretionary_aum=450000000.0,
            non_discretionary_aum=50000000.0,
            total_clients=250,
            high_net_worth_clients=50,
            pension_plan_clients=25,
            other_clients=175,
            reporting_date=date(2023, 12, 31)
        )
        
        assert financials.crd_number == 123456
        assert financials.assets_under_management == 500000000.0
        assert financials.discretionary_aum == 450000000.0
        assert financials.total_clients == 250
        assert financials.reporting_date == date(2023, 12, 31)
        
    def test_ria_services(self):
        \"\"\"Test RIAServices model.\"\"\"
        services = RIAServices(
            crd_number=123456,
            portfolio_management=True,
            financial_planning=True,
            pension_consulting=False,
            selection_of_advisors=True,
            publication_of_periodicals=False,
            security_ratings=False,
            market_timing=False,
            educational_seminars=True,
            other_services=["estate planning", "tax planning"]
        )
        
        assert services.crd_number == 123456
        assert services.portfolio_management is True
        assert services.financial_planning is True
        assert services.pension_consulting is False
        assert services.educational_seminars is True
        assert "estate planning" in services.other_services
        
    def test_ria_firm_composition(self):
        \"\"\"Test RIAFirm model composition.\"\"\"
        basic_info = RIABasicInfo(crd_number=123456, legal_name="Test Firm")
        address = Address(street="456 Oak St", city="Chicago", state="IL", zip_code="60601")
        contact = Contact(name="Jane Doe", title="President")
        
        firm = RIAFirm(
            basic_info=basic_info,
            addresses=[address],
            contacts=[contact]
        )
        
        assert firm.basic_info.crd_number == 123456
        assert len(firm.addresses) == 1
        assert firm.addresses[0].city == "Chicago"
        assert len(firm.contacts) == 1
        assert firm.contacts[0].name == "Jane Doe"
        
    def test_acquisition_score(self):
        \"\"\"Test AcquisitionScore model.\"\"\"
        score = AcquisitionScore(
            crd_number=123456,
            overall_score=85.5,
            category_scores={
                "assets_under_management": 90.0,
                "client_base": 80.0,
                "geographic_fit": 75.0,
                "service_offerings": 85.0,
                "fee_structure": 95.0,
                "regulatory_history": 90.0,
                "growth_potential": 70.0
            },
            last_updated=datetime(2024, 1, 15, 10, 30, 0),
            scoring_version="1.0.0",
            notes="Strong candidate for acquisition"
        )
        
        assert score.crd_number == 123456
        assert score.overall_score == 85.5
        assert len(score.category_scores) == 7
        assert score.category_scores["assets_under_management"] == 90.0
        assert score.scoring_version == "1.0.0"
        assert "Strong candidate" in score.notes
        

# Placeholder for future tests
def test_placeholder():
    \"\"\"Placeholder test for future implementation.\"\"\"
    pass"