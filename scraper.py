#!/usr/bin/env python3

import json
import re
import time
from typing import Optional, Set
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
import networkx as nx
from collections import deque
import pickle

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---- Config ----
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; soundcloud-scraper/1.0; +https://example.org)",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
}

CLIENT_ID_PATTERNS = [
    re.compile(r'client_id\s*[:=]\s*"([0-9a-zA-Z]{32})"'),
    re.compile(r'client_id\s*[:=]\s*\'([0-9a-zA-Z]{32})\''),
    re.compile(r'client_id=([0-9a-zA-Z]{32})'),
    re.compile(r'["\']client_id["\']\s*:\s*["\']([0-9a-zA-Z]{32})["\']'),
]
    
REQUEST_TIMEOUT = 20
POLITE_SLEEP = 0.2
RETRY_TOTAL = 6
RETRY_BACKOFF_FACTOR = 1.0

# ---- YOUR LIMITS ----
MAX_NODES_PER_ARTIST = 10_000
ARTIST_DIRECT_LIMIT = 10_00
MAX_NODES_PER_USER = 10_0


# ---- Artist Classification Function ----
### ARTIST LOGIC ADDED
def is_soundcloud_artist(user_obj: dict) -> bool:
    """Determine whether a SoundCloud user is an artist."""
    return (
        ((user_obj.get("track_count", 0) > 0
        and user_obj.get("followers_count", 0) > 1000)
        or user_obj.get("badges", {}).get("verified", False)
        or user_obj.get("verified", False))

    )

# ---- Utilities ----
def requests_session_with_retries() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=RETRY_TOTAL,
        read=RETRY_TOTAL,
        connect=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF_FACTOR,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(['GET', 'POST'])
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.headers.update(HEADERS)
    return s

def extract_client_id_from_text(text: str) -> Optional[str]:
    for pat in CLIENT_ID_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None

def find_client_id(session: requests.Session, profile_url: str, fallback: Optional[str] = None) -> Optional[str]:
    try:
        r = session.get(profile_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        print(f"Failed to fetch profile page: {e}")
        html = ""

    cid = extract_client_id_from_text(html)
    if cid:
        return cid

    script_urls = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
    for s in script_urls:
        s_url = urljoin(profile_url, s)
        try:
            rr = session.get(s_url, timeout=REQUEST_TIMEOUT)
            if rr.ok:
                cid = extract_client_id_from_text(rr.text)
                if cid:
                    return cid
        except Exception:
            continue

    blobs = re.findall(r'({".{50,}"}|(\[{"[^\]]{50,}\]))', html, re.DOTALL)
    for tup in blobs:
        blob = tup[0]
        cid = extract_client_id_from_text(blob)
        if cid:
            return cid

    return fallback

# ---- CORE BFS ----
# adjust bfs to get all the visited node edges and add them in as well to create the densest graph possible : ) 
def fetch_followers_bfs(
    session: requests.Session,
    client_id: str,
    graph: nx.DiGraph,
    visited: Set[str],
    queue: deque,
    current_artist: str,
    artist_start_node_count: int,
    root_user: str,
) -> None:

    while queue:
        current_total_nodes = graph.number_of_nodes()
        nodes_added_for_artist = current_total_nodes - artist_start_node_count

        if nodes_added_for_artist >= MAX_NODES_PER_ARTIST:
            print(f"[{current_artist}] Limit reached ({MAX_NODES_PER_ARTIST}).")
            return

        user_id = queue.popleft()
        if (user_id in visited and user_id !=root_user):
            continue

        visited.add(user_id)
        print(f"[{current_artist}] Processing {user_id} ({nodes_added_for_artist}/{MAX_NODES_PER_ARTIST})")

        # Followers / following API
        req_f = session.get(f"https://api-v2.soundcloud.com/users/{user_id}/followers?client_id={client_id}&limit=50")
        req_fl = session.get(f"https://api-v2.soundcloud.com/users/{user_id}/followings?client_id={client_id}&limit=50")

        if req_f.status_code != 200 or req_fl.status_code != 200:
            continue

        followers_list = req_f.json().get("collection", [])
        followings_list = req_fl.json().get("collection", [])
        
        # to make the graph denser convert followers and following list to sets and convert 
        # list of nodes in the graph to a set, take the intersection of both the followers
        # list and the following list and add the edges in : )
        # ADDED PLEASE CHECK THIS 
        followers_ids  = {str(obj["id"]) for obj in followers_list}
        followings_ids = {str(obj["id"]) for obj in followings_list}
        
        nodes = set(graph.nodes())
        followers_int = nodes.intersection(followers_ids)
        followings_int = nodes.intersection(followings_ids)
        
        # add the edges to a set and subtract both sets
        edges_set = set()
        for entry in followers_int: 
            edges_set.add((entry, user_id))    
    
        for entry in followings_int: 
            edges_set.add((user_id, entry))    
            
        edges_to_add = edges_set - set(graph.edges())
        
        for u,v in edges_to_add:
            graph.add_edge(u,v) 

        # ROOT special limit
        if user_id == root_user:
            followers_to_add = followers_list[:ARTIST_DIRECT_LIMIT]
            followings_to_add = followings_list[:ARTIST_DIRECT_LIMIT]
        else:
            followers_to_add = followers_list[:MAX_NODES_PER_USER]
            followings_to_add = followings_list[:MAX_NODES_PER_USER]

        max_len = max(len(followers_to_add), len(followings_to_add))

        for i in range(max_len):

            # --- STOP EARLY IF LIMIT HIT ---
            if graph.number_of_nodes() - artist_start_node_count >= MAX_NODES_PER_ARTIST:
                print(f"[{current_artist}] Limit hit mid-loop.")
                return

            # ---- FOLLOWERS ----
            if i < len(followers_to_add):
                f_obj = followers_to_add[i]
                fid = str(f_obj.get("id"))
                if fid:

                    ### ARTIST LOGIC ADDED
                    if not graph.has_node(fid):
                        graph.add_node(fid, is_artist=is_soundcloud_artist(f_obj))

                    graph.add_edge(fid, user_id)
                    if fid not in visited:
                        queue.append(fid)

            # ---- FOLLOWINGS ----
            if i < len(followings_to_add):
                fl_obj = followings_to_add[i]
                fid = str(fl_obj.get("id"))
                if fid:

                    ### ARTIST LOGIC ADDED
                    if not graph.has_node(fid):
                        graph.add_node(fid, is_artist=is_soundcloud_artist(fl_obj))

                    graph.add_edge(user_id, fid)
                    if fid not in visited:
                        queue.append(fid)

        time.sleep(POLITE_SLEEP)

#-utilized in analysis-#
def get_soundcloud_user(session, client_id, user_id: str):
    """Fetch full SoundCloud user details by user_id."""
    url = f"https://api-v2.soundcloud.com/users/{user_id}"
    params = {"client_id": client_id}
    r = session.get(url, params=params)

    if r.status_code != 200:
        return None

    return r.json()


# ---- RUN FOR ARTIST ----
def run_for_user(
    username: str,
    client_id: Optional[str],
    graph: nx.DiGraph,
    visited: Set[str], 
) -> Optional[str]:

    session = requests_session_with_retries()
    profile_url = f"https://soundcloud.com/{username}"

    print(f"\n=== ARTIST: {username} ===")

    # Discover client_id
    client_id = find_client_id(session, profile_url, fallback=client_id)
    print("Using client_id:", client_id)

    # Resolve to user_id
    r = session.get("https://api-v2.soundcloud.com/resolve",
                    params={"url": profile_url, "client_id": client_id})
    user_id = str(r.json().get("id"))
    print(f"Resolved {username} -> {user_id}")

    # Root artist marked as artist=True
    graph.add_node(user_id, username=username, is_artist=True)

    queue = deque([user_id])
    artist_start_node_count = graph.number_of_nodes()

    fetch_followers_bfs(
        session, client_id, graph, visited, queue,
        current_artist=username,
        artist_start_node_count=artist_start_node_count,
        root_user=user_id,
    )

    print(f"{username} done. Nodes added:",
          graph.number_of_nodes() - artist_start_node_count)

    return client_id

# ---- CLI ----
if __name__ == "__main__":

    artists = [
        "Futureisnow", "bigsean-1", "lana-del-rey", "walefolarin",
        "pushat", "bobatl", "bigkrit", "theweeknd", "justintimberlake", "calvinharris"
    ]

    graph = nx.DiGraph()
    visited = set()
    fallback_client_id = None

    print("Max nodes per artist:", MAX_NODES_PER_ARTIST)

    try:
        for artist in artists:
            fallback_client_id = run_for_user(
                artist, fallback_client_id, graph, visited
            )

        print("\n=== FINAL STATS ===")
        print("Total nodes:", graph.number_of_nodes())
        print("Total edges:", graph.number_of_edges())

        with open("soundcloud_graph.gpickle", "wb") as f:
            pickle.dump(graph, f)

    except KeyboardInterrupt:
        with open("partial_graph.gpickle", "wb") as f:
            pickle.dump(graph, f)
