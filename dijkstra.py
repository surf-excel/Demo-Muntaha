import heapq

def dijkstra(graph, start):
    """graph is a dict of node -> list of (neighbor, weight)."""
    distances = {node: float('inf') for node in graph}
    distances[start] = 0
    queue = [(0, start)]
    
    while queue:
        current_dist, node = heapq.heappop(queue)
        if current_dist > distances[node]:
            continue
        for neighbor, weight in graph[node]:
            distance = current_dist + weight
            if distance < distances[neighbor]:
                distances[neighbor] = distance
                heapq.heappush(queue, (distance, neighbor))
    return distances