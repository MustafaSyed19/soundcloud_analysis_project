#!/usr/bin/env python3

import json
import re
import time
import sqlite3
from typing import Optional, Dict, Any, Set
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
import networkx as nx
from collections import deque
import pickle


import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper import find_client_id, requests_session_with_retries, get_soundcloud_user

def pageRankScores(G):
    
    pageRankScores = nx.pagerank(G)
    
    sortedPageRankScores = sorted(pageRankScores.items(),
                                 key=lambda item: item[1],
                                 reverse=True
                                )

    return sortedPageRankScores[:20]


#generating FoF edges like A2 for successor
def generateFoF(graph):
    FoFedges = set()
    for node in graph.nodes():
        follows = set(graph.successors(node))
        for follower in follows:
            for recommended in graph.successors(follower):
                if recommended != node and recommended not in follows:
                    FoFedges.add((node, recommended))
    return list(FoFedges)

def generateFoFArtists(graph):
    FoFedges = set()
    for node in graph.nodes():
        follows = set(graph.successors(node))
        for follower in follows:
            for recommended in graph.successors(follower):
                if recommended != node and recommended not in follows:
                    if graph.nodes[recommended].get("is_artist") is True:
                        FoFedges.add((node, recommended))
    return list(FoFedges)

#pagerank artists only
def pageRankArtistSingle(graph, user, top_k=20):
    pr = nx.pagerank(graph, personalization={user: 1})
    existing = set(graph.successors(user))
    artistCandidates = [n for n, data in graph.nodes(data=True) if data.get("is_artist") is True]
    scores = {n: s for n, s in pr.items() if n != user and n not in existing and n in artistCandidates}
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

#pagerank all accounts
def pageRankSingle(graph, user, top_k=20):
    pr = nx.pagerank(graph, personalization={user: 1})
    existing = set(graph.successors(user))
    scores = {n: s for n, s in pr.items() if n != user and n not in existing}
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

#common neighbour
def generateCN(FoFedges, account):
    targetEdgeCN = [(u, v, len(list(nx.common_neighbors(UG, u, v)))) 
                    for u, v in FoFedges]
    targetEdgeCN = sorted(targetEdgeCN, key=lambda x: x[2], reverse=True)
    recommendCN = list()
    for node1, node2, score in targetEdgeCN:
        if node1 == account:
            recommendCN.append((node2, score))
    return recommendCN

if __name__ == "__main__":
        graph = pickle.load(open("soundcloud_graph.gpickle", "rb"))
        profile_url = "https://soundcloud.com/mcdonaldsusa"
        session =  requests_session_with_retries()
        client_id = find_client_id(session,profile_url=profile_url,fallback=None)

        node = list(graph.nodes())[0] #specified account
        topn = 5
        
        #link prediction common neighbour
        print("  → Common Neighbors...")
        UG = graph.to_undirected()
        FoFedges = generateFoFArtists(graph)
        recommendCN = generateCN(FoFedges, node)
        print("Recommended Artists")
        for node2, score in recommendCN[:topn]:
            user = get_soundcloud_user(session,client_id=client_id,user_id=node2)
            print(f"{user['username']}: {score}")

        #personalized pagerank
        print("  → PageRank...")
        print("Recommended Artists")
        pagerank = pageRankArtistSingle(graph, node, top_k=20)
        recommendPR = list()
        for node, score in pagerank[:topn]:
            user = get_soundcloud_user(session,client_id=client_id,user_id=node)
            print(f"{user['username']}: {score:.6f}")
            username = graph.nodes[node].get("username", None)