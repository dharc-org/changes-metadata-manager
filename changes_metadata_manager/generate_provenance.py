"""
Module to generate provenance snapshots from RDF data.
Loads RDF data in various formats from all files in a directory,
extracts all subjects, and creates provenance snapshots as named graphs
with type prov:Entity.
"""

import os
import datetime
from rdflib import Dataset, URIRef, Namespace, Literal
from rdflib.namespace import RDF, XSD, DCTERMS

def generate_provenance_snapshots(input_directory, output_file, input_format=None, output_format='nquads', agent_orcid=None, primary_source=None):
    """
    Generate provenance snapshots from RDF data.
    
    Args:
        input_directory: Path to directory containing RDF files
        output_file: Path to output file with provenance snapshots (N-Quads format)
        input_format: Optional format to use for all input files (overrides auto-detection)
        output_format: Format to use for output file (default: nquads)
        agent_orcid: ORCID of the responsible agent
        primary_source: URI of the primary source for the data
    """

    input_graph = Dataset()
    default_graph = input_graph.graph()
    
    file_count = 0
    
    rdf_extensions = {
        '.ttl': 'turtle',
        '.nt': 'nt',
        '.n3': 'n3',
        '.xml': 'xml',
        '.rdf': 'xml',
        '.jsonld': 'json-ld',
        '.nq': 'nquads',
        '.trig': 'trig'
    }
    
    for filename in os.listdir(input_directory):
        file_path = os.path.join(input_directory, filename)
                
        if input_format:
            format_name = input_format
        else:
            _, ext = os.path.splitext(filename.lower())
            format_name = rdf_extensions[ext]
        
        print(f"Processing {file_path} as {format_name}...")
        default_graph.parse(file_path, format=format_name)
        file_count += 1
    
    if file_count == 0:
        print(f"No valid RDF files found in {input_directory}")
        return
    
    print(f"Processed {file_count} RDF files")
    
    dataset = Dataset()
    
    PROV = Namespace('http://www.w3.org/ns/prov#')
    dataset.namespace_manager.bind('prov', PROV)
    dataset.namespace_manager.bind('dcterms', DCTERMS)
    
    for prefix, namespace in input_graph.namespace_manager.namespaces():
        dataset.namespace_manager.bind(prefix, namespace)
    
    subjects = set()
    for s, p, o in default_graph:
        if isinstance(s, URIRef):
            subjects.add(s)
    
    print(f"Found {len(subjects)} subjects in the input files")
    
    generation_time = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    
    responsible_agent = URIRef(agent_orcid)
    primary_source_uri = URIRef(primary_source)

    for subject in subjects:
        prov_graph_uri = URIRef(f"{subject}/prov/")
        
        snapshot_uri = URIRef(f"{subject}/prov/se/1")
        
        prov_graph = dataset.graph(identifier=prov_graph_uri)
        
        prov_graph.add((snapshot_uri, RDF.type, PROV.Entity))
        
        prov_graph.add((snapshot_uri, PROV.generatedAtTime, Literal(generation_time, datatype=XSD.dateTime)))
        
        prov_graph.add((snapshot_uri, PROV.wasAttributedTo, responsible_agent))
        
        prov_graph.add((snapshot_uri, PROV.hadPrimarySource, primary_source_uri))
        
        description = f"Entity <{str(subject)}> was created"
        prov_graph.add((snapshot_uri, DCTERMS.description, Literal(description, lang="en")))
    
    dataset.serialize(destination=output_file, format=output_format)
    print(f"Provenance snapshots saved to {output_file} in {output_format} format")