#!/usr/bin/env python3
"""
Tests for the provenance generator script.
"""

import os
import sys
import tempfile
import shutil
import pytest
from rdflib import Dataset, URIRef, Namespace
from rdflib.namespace import RDF

# Add the src directory to the path so we can import the module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from aldrovandi_provenance.generate_provenance import generate_provenance_snapshots

@pytest.fixture
def test_environment():
    """Set up test data and environment."""
    test_dir = tempfile.mkdtemp(dir='./tests/')
    test_ttl = os.path.join(test_dir, 'test_data.ttl')
    test_output = tempfile.mktemp(suffix='.nq')
    
    # Create test data file
    with open(test_ttl, 'w') as f:
        f.write("""
@prefix ex: <http://example.org/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .

ex:item1 a crm:E22_Human-Made_Object ;
    rdfs:label "Test Manuscript" .

ex:item2 a crm:E21_Person ;
    rdfs:label "John Doe" .
        """)
    
    yield {"test_dir": test_dir, "test_ttl": test_ttl, "test_output": test_output}
    
    # Clean up
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    if os.path.exists(test_output):
        os.remove(test_output)

def test_provenance_generation(test_environment):
    """Test that provenance snapshots are generated correctly."""
    # Get test environment variables
    test_dir = test_environment["test_dir"]
    test_output = test_environment["test_output"]
    
    # Generate provenance snapshots
    agent_orcid = "https://orcid.org/0000-0002-8420-0696"
    primary_source = "https://example.org/primary-source"
    generate_provenance_snapshots(test_dir, test_output, agent_orcid=agent_orcid, primary_source=primary_source)
    
    # Check that the output file was created
    assert os.path.exists(test_output), "Output file was not created"
    
    # Load the output file
    dataset = Dataset()
    dataset.parse(test_output, format='nquads')
    
    # Define namespaces
    PROV = Namespace('http://www.w3.org/ns/prov#')
    
    # Check that we have the expected named graphs
    expected_graphs = [
        URIRef('http://example.org/item1/prov/'),
        URIRef('http://example.org/item2/prov/')
    ]
    actual_graphs = [g.identifier for g in dataset.graphs()]

    for graph in expected_graphs:
        assert graph in actual_graphs, f"Expected graph {graph} not found"
    
    # Check that snapshots are typed as prov:Entity
    item1_prov_graph = dataset.graph(URIRef('http://example.org/item1/prov/'))
    item2_prov_graph = dataset.graph(URIRef('http://example.org/item2/prov/'))
    
    item1_snapshot = URIRef('http://example.org/item1/prov/se/1')
    item2_snapshot = URIRef('http://example.org/item2/prov/se/1')
    
    assert (item1_snapshot, RDF.type, PROV.Entity) in item1_prov_graph, "item1 snapshot is not typed as prov:Entity"
    assert (item2_snapshot, RDF.type, PROV.Entity) in item2_prov_graph, "item2 snapshot is not typed as prov:Entity"
    
    # Check for primary source relationship
    assert (item1_snapshot, PROV.hadPrimarySource, URIRef(primary_source)) in item1_prov_graph, "item1 snapshot missing primary source"
    assert (item2_snapshot, PROV.hadPrimarySource, URIRef(primary_source)) in item2_prov_graph, "item2 snapshot missing primary source"

def test_input_format_parameter(test_environment):
    """Test that the input_format parameter works correctly."""
    # Get test environment variables
    test_dir = test_environment["test_dir"]
    test_output = test_environment["test_output"]
    
    # Create a file with an unknown extension but containing Turtle content
    test_unknown = os.path.join(test_dir, 'unknown_format.xyz')
    with open(test_unknown, 'w') as f:
        f.write("""
@prefix ex: <http://example.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .

ex:item3 a crm:E22_Human-Made_Object ;
    rdfs:label "Test Object with Unknown Format" .
        """)
    
    # Generate provenance snapshots, specifying the format explicitly
    agent_orcid = "https://orcid.org/0000-0002-8420-0696"
    primary_source = "https://example.org/primary-source"
    generate_provenance_snapshots(test_dir, test_output, input_format='turtle', agent_orcid=agent_orcid, primary_source=primary_source)
    
    # Check that the output file was created
    assert os.path.exists(test_output), "Output file was not created"
    
    # Load the output file
    dataset = Dataset()
    dataset.parse(test_output, format='nquads')
    
    # Define namespaces
    PROV = Namespace('http://www.w3.org/ns/prov#')
    
    # Check that we have the expected named graph for item3
    item3_graph = URIRef('http://example.org/item3/prov/')
    actual_graphs = [g.identifier for g in dataset.graphs()]
    assert item3_graph in actual_graphs, f"Expected graph {item3_graph} not found"
    
    # Check that snapshot is typed as prov:Entity
    item3_prov_graph = dataset.graph(item3_graph)
    item3_snapshot = URIRef('http://example.org/item3/prov/se/1')
    assert (item3_snapshot, RDF.type, PROV.Entity) in item3_prov_graph, "item3 snapshot is not typed as prov:Entity"

def test_empty_directory(test_environment):
    """Test that the script handles empty directories correctly."""
    # Create an empty directory
    empty_dir = tempfile.mkdtemp(dir='./tests/')
    test_output = test_environment["test_output"]
    
    try:
        # Generate provenance snapshots for the empty directory
        agent_orcid = "https://orcid.org/0000-0002-8420-0696"
        primary_source = "https://example.org/primary-source"
        generate_provenance_snapshots(empty_dir, test_output, agent_orcid=agent_orcid, primary_source=primary_source)
        
        # Check that the output file was not created
        assert not os.path.exists(test_output), "Output file should not be created for empty directory"
    finally:
        # Clean up
        if os.path.exists(empty_dir):
            shutil.rmtree(empty_dir)

if __name__ == '__main__':
    pytest.main() 