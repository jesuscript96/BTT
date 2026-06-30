"""Tests del parser de insiders (SEC Forms 3/4/5) usado por Edgie.

Cubre el parseo del XML de ownership a filas estructuradas (nombre, rol,
transacción) que se inyectan en el prompt del informe de dilución para que
Edgie nombre a los directivos sin inventar.
"""

from app.routers.ticker_analysis import parse_form345_xml


FORM4_PURCHASE = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <periodOfReport>2024-05-10</periodOfReport>
  <issuer>
    <issuerName>Example Corp</issuerName>
    <issuerTradingSymbol>EXMP</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>Doe John A</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-05-10</value></transactionDate>
      <transactionCoding>
        <transactionCode>P</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>1.25</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


FORM3_HOLDING = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>3</documentType>
  <periodOfReport>2024-01-02</periodOfReport>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>Smith Jane</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isTenPercentOwner>1</isTenPercentOwner>
    </reportingOwnerRelationship>
  </reportingOwner>
</ownershipDocument>"""


def test_form4_purchase_is_parsed():
    rows = parse_form345_xml(FORM4_PURCHASE)
    assert len(rows) == 1
    r = rows[0]
    assert r["name"] == "Doe John A"
    assert "Director" in r["role"]
    assert "Officer (Chief Executive Officer)" in r["role"]
    assert r["form_type"] == "4"
    assert r["date"] == "2024-05-10"
    assert r["code"] == "P"
    assert r["code_label"] == "Compra en mercado abierto"
    assert r["shares"] == 10000.0
    assert r["price"] == 1.25
    assert r["acquired_disposed"] == "A"


def test_form3_without_transactions_emits_presence_row():
    rows = parse_form345_xml(FORM3_HOLDING)
    assert len(rows) == 1
    r = rows[0]
    assert r["name"] == "Smith Jane"
    assert "10% Owner" in r["role"]
    assert r["form_type"] == "3"
    assert r["code"] is None
    assert r["shares"] is None


def test_malformed_xml_returns_empty_list():
    assert parse_form345_xml("not xml at all <<<") == []
    assert parse_form345_xml("") == []
