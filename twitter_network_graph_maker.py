import networkx as nx
import pickle

# Load the graph
G = nx.read_edgelist(
    "twitter_combined.txt",
    nodetype=int,
    create_using=nx.DiGraph()
)

# Save to pickle
with open("twitter_combined_graph.gpickle", "wb") as f:
    pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)

print("Saved as twitter_combined_graph.gpickle")
