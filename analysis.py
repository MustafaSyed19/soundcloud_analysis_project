#!/usr/bin/env python3

import pickle
import networkx as nx

# Load the graph
print("Loading graph...")
with open(r"C:\Users\Mustafa Syed\Github repos\soundcloud_scraper\soundcloud_full_following_graph.gpickle", 'rb') as f:
    graph = pickle.load(f)

print(f"\n{'='*60}")
print("BASIC GRAPH STATISTICS")
print(f"{'='*60}")
print(f"Total nodes: {graph.number_of_nodes():,}")
print(f"Total edges: {graph.number_of_edges():,}")
print(f"Graph type: {'Directed' if graph.is_directed() else 'Undirected'}")

print(f"\n{'='*60}")
print("CONNECTED COMPONENTS ANALYSIS")
print(f"{'='*60}")

# For directed graphs, we have weakly and strongly connected components
if graph.is_directed():
    # Weakly connected components (treat as undirected)
    weak_components = list(nx.weakly_connected_components(graph))
    print(f"\nWeakly Connected Components: {len(weak_components)}")
    print("  (nodes connected by edges in either direction)")
    
    # Show size of each weak component
    weak_sizes = sorted([len(comp) for comp in weak_components], reverse=True)
    print(f"\n  Component sizes:")
    for i, size in enumerate(weak_sizes[:10], 1):  # Show top 10
        print(f"    Component {i}: {size:,} nodes ({size/graph.number_of_nodes()*100:.2f}%)")
    if len(weak_sizes) > 10:
        print(f"    ... and {len(weak_sizes) - 10} more components")
    
    # Strongly connected components (following directed paths)
    strong_components = list(nx.strongly_connected_components(graph))
    print(f"\n\nStrongly Connected Components: {len(strong_components)}")
    print("  (nodes connected by directed paths in both directions)")
    
    # Show size of each strong component
    strong_sizes = sorted([len(comp) for comp in strong_components], reverse=True)
    print(f"\n  Component sizes:")
    for i, size in enumerate(strong_sizes[:10], 1):  # Show top 10
        print(f"    Component {i}: {size:,} nodes ({size/graph.number_of_nodes()*100:.2f}%)")
    if len(strong_sizes) > 10:
        print(f"    ... and {len(strong_sizes) - 10} more components")
else:
    # For undirected graphs
    components = list(nx.connected_components(graph))
    print(f"\nConnected Components: {len(components)}")
    
    # Show size of each component
    comp_sizes = sorted([len(comp) for comp in components], reverse=True)
    print(f"\nComponent sizes:")
    for i, size in enumerate(comp_sizes[:10], 1):
        print(f"  Component {i}: {size:,} nodes ({size/graph.number_of_nodes()*100:.2f}%)")
    if len(comp_sizes) > 10:
        print(f"  ... and {len(comp_sizes) - 10} more components")

print(f"\n{'='*60}")