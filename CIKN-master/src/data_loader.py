import collections

import numpy as np
import os


def load_data(args):
    n_user, n_item, train_data, eval_data, test_data, user_history_dict = load_rating(args)
    n_entity, n_relation, adj_entity, adj_relation, kg = load_kg(args)
    ripple_set = get_ripple_set(args, kg, user_history_dict)
    print('data loaded.')

    return n_user, n_item, n_entity, n_relation, train_data, eval_data, test_data, adj_entity, adj_relation, ripple_set


def load_rating(args):
    print('reading rating file ...')

    # reading rating file
    rating_file = '../data/' + args.dataset + '/ratings_final'
    if os.path.exists(rating_file + '.npy'):
        rating_np = np.load(rating_file + '.npy')
    else:
        rating_np = np.loadtxt(rating_file + '.txt', dtype=np.int64)
        np.save(rating_file + '.npy', rating_np)

    n_user = len(set(rating_np[:, 0]))
    n_item = len(set(rating_np[:, 1]))
    train_data, eval_data, test_data, user_history_dict = dataset_split(rating_np, args)

    return n_user, n_item, train_data, eval_data, test_data, user_history_dict


def dataset_split(rating_np, args):
    print('splitting dataset ...')

    # train:eval:test = 6:2:2
    eval_ratio = 0.2
    test_ratio = 0.2
    n_ratings = rating_np.shape[0]

    eval_indices = np.random.choice(list(range(n_ratings)), size=int(n_ratings * eval_ratio), replace=False)
    left = set(range(n_ratings)) - set(eval_indices)
    test_indices = np.random.choice(list(left), size=int(n_ratings * test_ratio), replace=False)
    train_indices = list(left - set(test_indices))
    if args.ratio < 1:
        train_indices = np.random.choice(list(train_indices), size=int(len(train_indices) * args.ratio), replace=False)

    # traverse training data, only keeping the users with positive ratings
    user_history_dict = dict()
    for i in train_indices:
        user = rating_np[i][0]
        item = rating_np[i][1]
        rating = rating_np[i][2]
        if rating == 1:
            if user not in user_history_dict:
                user_history_dict[user] = []
            user_history_dict[user].append(item)

    train_indices = [i for i in train_indices if rating_np[i][0] in user_history_dict]
    eval_indices = [i for i in eval_indices if rating_np[i][0] in user_history_dict]
    test_indices = [i for i in test_indices if rating_np[i][0] in user_history_dict]

    train_data = rating_np[train_indices]
    eval_data = rating_np[eval_indices]
    test_data = rating_np[test_indices]

    return train_data, eval_data, test_data, user_history_dict


def load_kg(args):
    print('reading KG file ...')

    # reading kg file
    kg_file = '../data/' + args.dataset + '/kg_final'
    if os.path.exists(kg_file + '.npy'):
        kg_np = np.load(kg_file + '.npy')
    else:
        kg_np = np.loadtxt(kg_file + '.txt', dtype=np.int64)
        np.save(kg_file + '.npy', kg_np)

    n_entity = len(set(kg_np[:, 0]) | set(kg_np[:, 2]))
    n_relation = len(set(kg_np[:, 1]))

    kg = construct_kg(kg_np)
    adj_entity, adj_relation = construct_adj(args, kg, n_entity)

    return n_entity, n_relation, adj_entity, adj_relation, kg


def construct_kg(kg_np):
    print('constructing knowledge graph ...')
    kg = dict()
    for triple in kg_np:
        head = triple[0]
        relation = triple[1]
        tail = triple[2]
        # treat the KG as an undirected graph
        if head not in kg:
            kg[head] = []
        kg[head].append((tail, relation))
        if tail not in kg:
            kg[tail] = []
        kg[tail].append((head, relation))
    return kg


def construct_adj(args, kg, entity_num):
    print('constructing adjacency matrix ...')
    # each line of adj_entity stores the sampled neighbor entities for a given entity
    # each line of adj_relation stores the corresponding sampled neighbor relations
    adj_entity = np.zeros([entity_num, args.neighbor_sample_size], dtype=np.int64)
    adj_relation = np.zeros([entity_num, args.neighbor_sample_size], dtype=np.int64)
    for entity in range(entity_num):
        neighbors = kg[entity]
        n_neighbors = len(neighbors)
        if n_neighbors >= args.neighbor_sample_size:
            sampled_indices = np.random.choice(list(range(n_neighbors)), size=args.neighbor_sample_size, replace=False)
        else:
            sampled_indices = np.random.choice(list(range(n_neighbors)), size=args.neighbor_sample_size, replace=True)
        adj_entity[entity] = np.array([neighbors[i][0] for i in sampled_indices])
        adj_relation[entity] = np.array([neighbors[i][1] for i in sampled_indices])

    return adj_entity, adj_relation


def get_ripple_set(args, kg, user_history_dict):
    print('constructing ripple set ...')

    # user -> [(hop_0_heads, hop_0_relations, hop_0_tails), (hop_1_heads, hop_1_relations, hop_1_tails), ...]
    ripple_set = collections.defaultdict(list)

    for user in user_history_dict:
        for h in range(args.n_iter):
            memories_h = []
            memories_r = []
            memories_t = []

            if h == 0:
                tails_of_last_hop = user_history_dict[user]
            else:
                tails_of_last_hop = ripple_set[user][-1][2]

            for entity in tails_of_last_hop:
                for tail_and_relation in kg[entity]:
                    memories_h.append(entity)
                    memories_r.append(tail_and_relation[1])
                    memories_t.append(tail_and_relation[0])

            # if the current ripple set of the given user is empty, we simply copy the ripple set of the last hop here
            # this won't happen for h = 0, because only the items that appear in the KG have been selected
            # this only happens on 154 users in Book-Crossing dataset (since both BX dataset and the KG are sparse)
            if len(memories_h) == 0:
                ripple_set[user].append(ripple_set[user][-1])
            else:
                # sample a fixed-size 1-hop memory for each user
                replace = len(memories_h) < args.neighbor_sample_size
                indices = np.random.choice(len(memories_h), size=args.neighbor_sample_size, replace=replace)
                memories_h = [memories_h[i] for i in indices]
                memories_r = [memories_r[i] for i in indices]
                memories_t = [memories_t[i] for i in indices]
                ripple_set[user].append((memories_h, memories_r, memories_t))

    return ripple_set