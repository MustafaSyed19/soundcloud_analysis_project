import igraph as ig  
import matplotlib.pyplot as plt
import pickle
import itertools
from pathlib import Path
import statistics
import random
from collections import Counter,defaultdict,deque
import matplotlib.pyplot as plt
import numpy as np 
import igraph as ig
import random
import numpy as np
from matplotlib.patches import Ellipse
from scipy.spatial import ConvexHull
from scraper import find_client_id, requests_session_with_retries, get_soundcloud_user


def spaced_layout(g):

    layout = g.layout("fr")  # default FR layout

    coords = np.array(layout.coords, dtype=float)
    
    return coords

def plot_blobs_and_nodes(g, communities, title):
    print(f"🎨 Generating side-by-side plot: {title}")

    coords = spaced_layout(g)
    x = coords[:,0]
    y = coords[:,1]

    # FIXED plot limits for both subplots
    x_min, x_max = x.min(), x.max()
    y_min, y_max = y.min(), y.max()

    # Add padding so blobs have room
    pad_x = (x_max - x_min) * 0.1
    pad_y = (y_max - y_min) * 0.1

    membership = np.array(communities.membership)
    num_comms = len(communities)
    palette = ig.drawing.colors.RainbowPalette(num_comms)

    fig, (ax_blobs, ax_nodes) = plt.subplots(1, 2, figsize=(18, 9))

    # -------------------------------------------------
    # LEFT: BLOBS
    # -------------------------------------------------
    ax_blobs.set_title("Community Blobs")
    ax_blobs.axis("off")

    # Set fixed limits BEFORE plotting
    ax_blobs.set_xlim(x_min - pad_x, x_max + pad_x)
    ax_blobs.set_ylim(y_min - pad_y, y_max + pad_y)

    for comm_id in range(num_comms):
        nodes = np.where(membership == comm_id)[0]
        if len(nodes) < 5:
            continue

        pts = coords[nodes]

        cx, cy = pts[:,0].mean(), pts[:,1].mean()
        rx = pts[:,0].std() * 3
        ry = pts[:,1].std() * 3

        rx = max(rx, 0.1)
        ry = max(ry, 0.1)

        color = palette.get(comm_id)
        ell = Ellipse((cx, cy), rx, ry,
                      facecolor=color, alpha=0.18,
                      edgecolor=color, linewidth=1)
        ax_blobs.add_patch(ell)

    # -------------------------------------------------
    # RIGHT: NODES
    # -------------------------------------------------
    ax_nodes.set_title("Nodes Colored by Community")
    ax_nodes.axis("off")

    # Same fixed limits
    ax_nodes.set_xlim(x_min - pad_x, x_max + pad_x)
    ax_nodes.set_ylim(y_min - pad_y, y_max + pad_y)

    node_colors = [palette.get(m) for m in membership]
    ax_nodes.scatter(coords[:,0], coords[:,1], s=3, c=node_colors, alpha=0.85)

    # -------------------------------------------------
    # SAVE IMAGE
    # -------------------------------------------------
    out_file = f"{title}_sidebyside.png"
    plt.savefig(out_file, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"✅ Saved: {out_file}")

def nx_to_igraph(nx_graph):
    # 1. Create igraph with all nodes and their names matching NX nodes
    ig_graph = ig.Graph(directed=nx_graph.is_directed())
    ig_graph.add_vertices(list(nx_graph.nodes()))

    # 2. Add edges
    edges = list(nx_graph.edges())
    ig_graph.add_edges(edges)

    # 3. Copy all node attributes
    for node in nx_graph.nodes():
        for attr, value in nx_graph.nodes[node].items():
            ig_graph.vs.find(name=node)[attr] = value
    return ig_graph


def spit(graph, title):
    """
    Processes the graph and outputs statistics + charts.

    Updates:
    - Corrected degree distribution to plot degree vs. count-of-nodes
    - Cleaned PageRank top-50 slicing
    - Cleaned clustering histogram bin labeling
    """
    # ig_graph = ig.Graph.TupleList(graph.edges(),directed = graph.is_directed())
    #comment the line below above in if doing for twitter and comment line below out and 
    #vice versa 
    ig_graph = nx_to_igraph(graph)
    artists = ig_graph.vs.select(is_artist=True)

    
    #basic stats 
    
    print(title + " initial stats")
    print("# nodes:", ig_graph.vcount())
    print("# edges:", ig_graph.ecount())
    print("# artist nodes", len(artists))
    print("density:", ig_graph.density())
    print("avg in-degree:", statistics.mean(ig_graph.degree(mode="in")))
    print("avg out-degree:", statistics.mean(ig_graph.degree(mode="out")))
    print("max degree:", max(ig_graph.degree()))
    print("median degree:", statistics.median(ig_graph.degree()))
    print("reciprocity:", ig_graph.reciprocity())
    g_und = ig_graph.as_undirected()
    print("global clustering:", g_und.transitivity_undirected())    
    print("degree assortativity:", g_und.assortativity_degree())
    
    # components
    wc = ig_graph.components(mode="weak")
    print("weak components:", len(wc))
    print("largest weak component:", max(wc.sizes()))

    sc = ig_graph.components(mode="strong")
    print("strong components:", len(sc))
    print("largest strong component:", max(sc.sizes()))

    # approximate APL + diameter
    sample_size = ig_graph.vcount()//10
    sample_nodes = random.sample(range(ig_graph.vcount()), sample_size)

    sub = ig_graph.subgraph(sample_nodes)
    print("approx APL:", sub.average_path_length())
    print("approx diameter:", sub.diameter())
    
    #graphs 
    degree_counts = Counter(ig_graph.degree()) 
    n = ig_graph.vcount()
    pk = {k: c / n for k, c in degree_counts.items()}
    
    deg = list(degree_counts.keys())
    cnt = list(degree_counts.values())
    
    plt.bar(deg, cnt)
    plt.xlabel("Degree k")
    plt.ylabel("Number of nodes with degree k") 
    plt.title("Degree Distribution")
    plt.show()
    plt.bar(deg, cnt)
        
    plt.loglog(deg, cnt, linestyle='None')
    plt.xlabel("Degree k (log)")
    plt.ylabel("Number of nodes (log)")
    plt.title("Degree Distribution (Log–Log Scale)")
    plt.show()
    
    
    pagerank_scores = ig_graph.pagerank()
    authority, hub = ig_graph.authority_score(), ig_graph.hub_score()
    
    plt.figure(figsize=(15,4))

    plt.subplot(1,3,1)
    plt.hist(pagerank_scores, bins=40)
    plt.xscale("log")
    plt.yscale("log")
    plt.title("PageRank Distribution (Log–Log)")
    plt.xlabel("Score (log)")
    plt.ylabel("Frequency (log)")

    plt.subplot(1,3,2)
    plt.hist(authority, bins=40)
    plt.xscale("log")
    plt.yscale("log")
    plt.title("Authority Score Distribution (Log–Log)")
    plt.xlabel("Score (log)")

    plt.subplot(1,3,3)
    plt.hist(hub, bins=40)
    plt.xscale("log")
    plt.yscale("log")
    plt.title("Hub Score Distribution (Log–Log)")
    plt.xlabel("Score (log)")

    plt.tight_layout()
    plt.show()
    for v in ig_graph.vs:
        print(v.index, v.attributes())


    #this is just some random profile to get a clientId from 
    profile_url = "https://soundcloud.com/mcdonaldsusa"
    session =  requests_session_with_retries()
    client_id = find_client_id(session,profile_url=profile_url,fallback=None) 
        
    
    # ---- Top 10 PageRank ----
    
    top_pr_idx = np.argsort(pagerank_scores)[-10:][::-1]
    print("🔴 Top 10 PageRank Nodes:")
    for i in top_pr_idx:
        print(f"Node {i} — PageRank Score: {pagerank_scores[i]:.6f}")
        node_id = ig_graph.vs[i]["name"]
        score = pagerank_scores[i]
        print(f"Vertex {i}, UserID={node_id}, PageRank={score}")
        #comment this out for twitter
        print(get_soundcloud_user(session,client_id=client_id,user_id=node_id))
        
    print("\n")

    # ---- Top 10 Authority ----
    top_auth_idx = np.argsort(authority)[-10:][::-1]
    print("🔵 Top 10 Authority Nodes:")
    for i in top_auth_idx:
        print(f"Node {i} — Authority Score: {authority[i]:.6f}")
        node_id = ig_graph.vs[i]["name"]
        score = authority[i]
        print(f"Vertex {i}, UserID={node_id}, Authority={score}")
        #comment this out for twitter
        print(get_soundcloud_user(session,client_id=client_id,user_id=node_id))
    print("\n")

    # ---- Top 10 Hubs ----
    top_hub_idx = np.argsort(hub)[-10:][::-1]
    print("🟢 Top 10 Hub Nodes:")
    for i in top_hub_idx:
        print(f"Node {i} — Hub Score: {hub[i]:.6f}")
        node_id = ig_graph.vs[i]["name"]
        score = hub[i]
        print(f"Vertex {i}, UserID={node_id}, Hub={score}")
        #comment this out for twitter
        print(get_soundcloud_user(session,client_id=client_id,user_id=node_id))

    import time
    #community detection 
    print("\n==============================")
    print("🌐 COMMUNITY DETECTION")
    print("==============================")

    
    # ---- Louvain (recommended) ----
    start = time.time()

    comms_louvain = (ig_graph.as_undirected()).community_multilevel()
    print(f"Louvain communities: {len(comms_louvain)}")
    print("Sizes:", sorted(comms_louvain.sizes(), reverse=True)[:10])
    print(f"⏱ Louvain time: {time.time()-start:.3f}s")

    # ---- Leiden ----
    start = time.time()
    comms_leiden = (ig_graph.as_undirected()).community_leiden()
    print(f"\nLeiden communities: {len(comms_leiden)}")
    print("Sizes:", sorted(comms_leiden.sizes(), reverse=True)[:10])
    print(f"⏱ Leiden time: {time.time()-start:.3f}s")

    # ---- Infomap ----
    start = time.time()
    comms_infomap = ig_graph.community_infomap()
    print(f"\nInfoMap communities: {len(comms_infomap)}")
    print("Sizes:", sorted(comms_infomap.sizes(), reverse=True)[:10])
    print(f"⏱ InfoMap time: {time.time()-start:.3f}s")

    # ---- Label Propagation ----
    start = time.time()
    comms_lp = (ig_graph.as_undirected()).community_label_propagation()
    print(f"\nLabel Propagation communities: {len(comms_lp)}")
    print("Sizes:", sorted(comms_lp.sizes(), reverse=True)[:10])
    print(f"⏱ Label Prop: {time.time()-start:.3f}s")

    plot_blobs_and_nodes(g_und, comms_louvain, f"{title}_louvain_communities")
    plot_blobs_and_nodes(g_und, comms_leiden, f"{title}_leiden_communities")
    plot_blobs_and_nodes(g_und, comms_lp, f"{title}_lp_communities")
    plot_blobs_and_nodes(g_und, comms_infomap, f"{title}_InfoMap_communities")
    
    
    
if __name__ == "__main__":
    graph = pickle.load(open('twitter_combined_graph.gpickle', 'rb'))
    spit(graph, "Twitter Network")
    sc_graph = pickle.load(open('soundcloud_graph.gpickle', 'rb'))    
    spit(sc_graph, "Soundcloud Network")
