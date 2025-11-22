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

# Graph constraints
MAX_NODES_PER_ARTIST = 10000    # max nodes to explore per artist in BFS
MAX_FOLLOWERS_PER_USER = 100   # max followers to fetch from any single user

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

def normalize_next_href(next_href: str, client_id: str) -> str:
    if not next_href:
        return ""
    parsed = urlparse(next_href)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["client_id"] = [client_id]
    new_qs = urlencode({k: v[0] for k, v in qs.items()})
    return parsed._replace(query=new_qs).geturl()

# ---- Core BFS Function ----
def fetch_followers_bfs(
    session: requests.Session,
    client_id: str,
    graph: nx.DiGraph,
    visited: Set[str],
    queue: deque,
    current_artist: str,
    artist_start_node_count: int,
) -> None:
    """
    BFS fetch of followers with two constraints:
    1. MAX_FOLLOWERS_PER_USER: limit followers fetched from each individual user
    2. MAX_NODES_PER_ARTIST: limit total nodes explored for this artist
    """
    
    while queue:
        # Calculate how many nodes we've added for this artist
        current_total_nodes = graph.number_of_nodes()
        nodes_added_for_artist = current_total_nodes - artist_start_node_count
        
        # Check per-artist cap
        if nodes_added_for_artist >= MAX_NODES_PER_ARTIST:
            print(f"[{current_artist}] Reached per-artist cap: {nodes_added_for_artist}/{MAX_NODES_PER_ARTIST} nodes. Done.")
            return
        
        # Get next user to process
        user_id = queue.popleft()
        
        # Skip if already visited
        if user_id in visited:
            continue
        
        # Mark as visited
        visited.add(user_id)
        
        print(f"[{current_artist}] Processing user {user_id} (total progress: {nodes_added_for_artist}/{MAX_NODES_PER_ARTIST})")
        
        # Fetch followers for this user (with per-user limit)
        follow_next_url = f"https://api-v2.soundcloud.com/users/{user_id}/followers?client_id={client_id}&limit=50"
        following_next_url = f"https://api-v2.soundcloud.com/users/{user_id}/followings?client_id={client_id}&limit=50"

        # Make API request for followers
        try:
            follower_data = session.get(follow_next_url, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            print(f"[{current_artist}] Follower request failed for user {user_id}: {e}")
            time.sleep(5)
            continue
        
        if follower_data.status_code in (401, 403):
            print(f"[{current_artist}] Auth error {follower_data.status_code} for user {user_id}. Skipping.")
            continue
            
        elif follower_data.status_code != 200:
            print(f"[{current_artist}] Error {follower_data.status_code} for user {user_id}. Skipping.")
            time.sleep(5)
            continue
        
        # Make API request for followings
        try:
            following_data = session.get(following_next_url, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            print(f"[{current_artist}] Following list request failed for user {user_id}: {e}")
            time.sleep(5)
            continue
            
        if following_data.status_code in (401, 403):
            print(f"[{current_artist}] Auth error {following_data.status_code} for user {user_id}. Skipping.")
            continue
            
        elif following_data.status_code != 200:
            print(f"[{current_artist}] Error {following_data.status_code} for user {user_id}. Skipping.")
            time.sleep(5)
            continue
        
        # Parse follower data
        try:
            follower_data_json = follower_data.json()
        except Exception as e:
            print(f"[{current_artist}] Follower JSON parse error: {e}")
            time.sleep(5)
            continue
        
        # Get followers collection
        follower_data_list = follower_data_json.get("collection", [])
        if not isinstance(follower_data_list, list):
            follower_data_list = []
        
        # Parse following data
        try:
            following_data_json = following_data.json()
        except Exception as e:
            print(f"[{current_artist}] Following JSON parse error: {e}")
            time.sleep(5)
            continue
            
        # Get followings collection
        following_data_list = following_data_json.get("collection", [])
        if not isinstance(following_data_list, list):
            following_data_list = []

        # Limit both lists
        followers_to_add = follower_data_list[:MAX_FOLLOWERS_PER_USER]
        followings_to_add = following_data_list[:MAX_FOLLOWERS_PER_USER]

        # Alternate between adding followers and followings
        max_len = max(len(followers_to_add), len(followings_to_add))
        
        followers_added = 0
        followings_added = 0

        for i in range(max_len):
            # Add follower if available
            if i < len(followers_to_add):
                follower_id = str(followers_to_add[i].get("id"))
                if follower_id:
                    graph.add_edge(follower_id, user_id)
                    if follower_id not in visited:
                        queue.append(follower_id)
                        followers_added += 1
                        print(f"[{current_artist}] Added FOLLOWER {follower_id} -> {user_id}")
            
            # Add following if available
            if i < len(followings_to_add):
                following_id = str(followings_to_add[i].get("id"))
                if following_id:
                    graph.add_edge(user_id, following_id)
                    if following_id not in visited:
                        queue.append(following_id)
                        followings_added += 1
                        print(f"[{current_artist}] Added FOLLOWING {user_id} -> {following_id}")
        
        print(f"[{current_artist}] Summary for user {user_id}: {followers_added} followers, {followings_added} followings added to queue")
        time.sleep(POLITE_SLEEP)
        
def run_for_user(
    username: str,
    client_id: Optional[str],
    graph: nx.DiGraph,
    visited: Set[str], 
) -> Optional[str]:
    session = requests_session_with_retries()
    profile_url = f"https://soundcloud.com/{username}"

    print(f"\n{'='*60}")
    print(f"Processing artist: {username}")
    print(f"{'='*60}")
    
    # Find client_id
    print("Discovering client_id...")
    discovered = find_client_id(session, profile_url, fallback=client_id)
    if not discovered:
        raise RuntimeError("Could not discover a client_id. Provide one with --client-id.")
    client_id = discovered
    print(f"Using client_id: {client_id}")

    # Resolve username to user ID
    resolve_url = "https://api-v2.soundcloud.com/resolve"
    params = {"url": profile_url, "client_id": client_id}
    print("Resolving user ID...")
    
    try:
        r = session.get(resolve_url, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        userobj = r.json()
    except Exception as e:
        raise RuntimeError(f"Failed to resolve username {username}: {e}")
    
    user_id = userobj.get("id")
    if user_id is None:
        raise RuntimeError("Resolve returned no ID.")
    user_id = str(user_id)
    print(f"Resolved {username} -> ID {user_id}")

    # Track starting node count
    artist_start_node_count = graph.number_of_nodes()
    
    # Add artist node to graph
    graph.add_node(user_id, username=username, artist=username, is_artist=True)

    # Initialize BFS queue with the artist
    queue = deque([user_id])
    
    # Run BFS
    print(f"Starting BFS for {username}...")
    fetch_followers_bfs(
        session=session,
        client_id=client_id,
        graph=graph,
        visited=visited,
        queue=queue,
        current_artist=username,
        artist_start_node_count=artist_start_node_count, 
    )

    # Report results
    nodes_added = graph.number_of_nodes() - artist_start_node_count
    print(f"\n[{username}] Finished!")
    print(f"  Nodes added: {nodes_added}")
    print(f"  Total nodes: {graph.number_of_nodes()}")
    print(f"  Total edges: {graph.number_of_edges()}")
    
    return client_id

# ---- CLI ----
if __name__ == "__main__":
    # Top 10 SoundCloud artists
    artists = [
        "Futureisnow", "bigsean-1", "lana-del-rey", "walefolarin",
        "pushat", "bobatl", "bigkrit", "theweeknd", "justintimberlake", "calvinharris"
    ]

    # Initialize global state
    graph = nx.DiGraph()
    visited = set()
    fallback_client_id = None

    print("="*60)
    print("SoundCloud Follower Network Scraper")
    print(f"Max nodes per artist: {MAX_NODES_PER_ARTIST}")
    print(f"Max followers per user: {MAX_FOLLOWERS_PER_USER}")
    print("="*60)

    try:
        for i, artist in enumerate(artists, start=1):
            print(f"\n{'#'*60}")
            print(f"Artist {i}/{len(artists)}: {artist}")
            print(f"{'#'*60}")

            # Run for this artist
            fallback_client_id = run_for_user(
                username=artist,
                client_id=fallback_client_id,
                graph=graph,
                visited=visited,
            )

        
        # Save final graph
        print(f"\n{'='*60}")
        print("FINAL STATISTICS")
        print(f"{'='*60}")
        print(f"Total nodes: {graph.number_of_nodes()}")
        print(f"Total edges: {graph.number_of_edges()}")
        print(f"{'='*60}")
        
        # Save to file
        output_file = "soundcloud_full_following_graph.gpickle"
        with open(output_file,'wb') as f: 
            pickle.dump(graph, f, pickle.HIGHEST_PROTOCOL)
        print(f"\nGraph saved to: {output_file}")
        
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Saving progress...")

        print("Partial graph saved to: soundcloud_follower_graph_partial.gpickle")
    except Exception as e:
        print(f"\nError occurred: {e}")
        import traceback
        traceback.print_exc()
        raise