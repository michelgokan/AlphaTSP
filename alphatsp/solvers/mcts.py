import copy
import random
import math

import numpy as np
import torch

import torch_geometric
from torch_geometric.data import Data


class MCTSNode:

	def __init__(self, p=None, t=[0], r=None, tsp=None, thresh=None):
		self.parent = p
		self.tsp = tsp
		self.tour = t
		self.remaining = r if r is not None else list(range(1, tsp.n))
		self.visits = 0
		self.total_score = 0
		self.avg_score = 1 / (len(self.remaining)+1)
		self.c = 0.7
		self.n = tsp.n
		self.children = []
		self.graph = None
		self.action = self.tour[-1]
		self.thresh = thresh

	def expand(self):
		k = random.choice(self.remaining)
		t = copy.copy(self.tour)
		r = copy.copy(self.remaining)
		t.append(k)
		r.remove(k)
		child = MCTSNode(self, t, r, self.tsp, self.thresh)
		self.children.append(child)
		return child

	def add_child(self, k):
		for child in self.children:
			if child.action == k:
				return child
		t = copy.copy(self.tour)
		r = copy.copy(self.remaining)
		t.append(k)
		r.remove(k)
		child = MCTSNode(self, t, r, self.tsp, self.thresh)
		self.children.append(child)
		return child

	def backprop(self, reward):
		self.visits += 1
		self.total_score += reward
		self.avg_score = self.total_score / self.visits
		if self.parent is not None:
			self.parent.backprop(reward)

	def simulate(self):
		random.shuffle(self.remaining)
		t = self.tour + self.remaining + [0]
		if self.thresh is None:
			return self.tsp.payoff(t)
		else:
			return self.tsp.tour_length(t) < self.thresh

	def has_children(self):
		return len(self.children) != 0

	def is_leaf(self):
		return len(self.tour) == self.n

	def is_fully_expanded(self):
		return len(self.remaining) == len(self.children)

	def get_tour(self):
		return self.tour + [self.tour[0]]

	def best_child_score(self):
		return max(self.children, key = lambda child: child.avg_score)

	def best_child_uct(self):
		k = math.log(self.visits)
		return max(self.children, key = lambda child: child.avg_score + self.c * math.sqrt(2 * k / child.visits))

	def best_child_visits(self):
		return max(self.children, key = lambda child: child.visits)

	def best_child_policy(self, model):
		if len(self.children) == 0: raise Exception("No children to select from.")
		if len(self.children) == 1: return self.children[0]

		model.eval()

		actions = [child.action for child in self.children]
		r = list(set.intersection(set(actions), set(self.remaining)))
		z = np.zeros(self.n, dtype=np.int)
		z[r] = 1
		z = z[self.remaining]

		graph = self.construct_graph()
		pred, _ = model(graph)

		pred = pred.squeeze()[z]
		selection = torch.argmax(pred)

		return self.children[selection]

	def select_child_policy(self, model):
		if len(self.children) == 0: raise Exception("No children to select from.")
		if len(self.children) == 1: return self.children[0]

		model.eval()

		actions = [child.action for child in self.children]
		r = list(set.intersection(set(actions), set(self.remaining)))
		z = np.zeros(self.n, dtype=np.int)
		z[r] = 1
		z = z[self.remaining]

		graph = self.construct_graph()
		pred, _ = model(graph)

		pred = pred.squeeze()[z]
		selection = torch.multinomial(pred, 1)
		return self.children[selection]

	def best_remaining_policy(self, model):
		if len(self.remaining) == 0: raise Exception("No remaining to select from.")
		if len(self.remaining) == 1: return self.add_child(self.remaining[0])

		model.eval()

		graph = self.construct_graph()
		pred, _ = model(graph)

		selection = torch.argmax(pred.squeeze()).item()
		selection = self.remaining[selection]

		return self.add_child(selection)

	def select_remaining_policy(self, model):
		if len(self.remaining) == 0: raise Exception("No remaining to select from.")
		if len(self.remaining) == 1: return self.add_child(self.remaining[0])

		model.eval()

		graph = self.construct_graph()
		pred, _ = model(graph)

		selection = torch.argmax(pred.squeeze()).item()
		selection = self.remaining[selection]

		selection = torch.multinomial(pred.squeeze(), 1)
		return self.add_child(selection)

	def construct_graph(self):
		if self.graph is not None:
			return self.graph

		points = torch.tensor(self.tsp.points).to(dtype=torch.float)

		edges = torch.zeros((2, len(self.tour)-1), dtype=torch.long)
		for i in range(len(self.tour)-1):
			edges[0, i] = self.tour[i]
			edges[1, i] = self.tour[i+1]

		choices = torch.zeros(self.n, dtype=torch.uint8)
		choices[self.remaining] = 1

		x = torch.cat([points, choices.unsqueeze(-1).to(dtype=torch.float)], dim=-1)

		self.graph = Data(x=x, pos=points, edge_index=edges, y=choices)

		return self.graph

class MCTSSolver:
    
    def __init__(self, tsp, iterations=1000):
        self.tsp = tsp
        self.root_node = MCTSNode(tsp=self.tsp)
        self.iterations = iterations
    
    def solve(self):
        node = self.root_node
        while not node.is_leaf():
            node = self.mcts_search(node)
        mcts_tour = node.get_tour()
        mcts_payoff = self.tsp.tour_length(mcts_tour)
        return mcts_tour, mcts_payoff

    def mcts_search(self, start_node):
        for _ in range(self.iterations):
            node = self.tree_policy(start_node)
            pay = node.simulate()
            node.backprop(pay)
        return start_node.best_child_score()

    def tree_policy(self, start_node):
        node = start_node
        while not node.is_leaf():
            if not node.is_fully_expanded():
                return node.expand()
            else:
                node = node.best_child_uct()
        return node