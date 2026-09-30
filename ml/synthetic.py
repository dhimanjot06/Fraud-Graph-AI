"""Synthetic transaction networks with *known* planted fraud rings.

Public fraud datasets rarely include ground-truth ring structure. This module
produces a realistic-looking background of ordinary payments and hides a
configurable number of rings inside it, so detectors can be measured against
the truth.

Planted patterns
  cycle      Money travels A -> B -> C -> A with near-identical amounts.
  collector  Many accounts send similar amounts to one mule, which forwards
             the pooled money to a single beneficiary.

Ring accounts also make ordinary payments to outsiders (camouflage), and all
ring amounts sit inside the normal amount range, so no single transaction
looks odd on its own.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _account_ids(n, prefix="AC"):
    return [f"{prefix}{1000 + i}" for i in range(n)]


def generate(n_accounts=600, n_normal=6000, n_cycle_rings=3, n_collector_rings=2,
             days=45, seed=7, start="2026-07-01"):
    """Return ``(transactions_df, truth)``.

    ``truth`` is a list of dicts: ``{"ring_id", "type", "accounts", "tx_ids"}``.
    """
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(start)
    accounts = _account_ids(n_accounts)
    n_ring_accounts = n_cycle_rings * 5 + n_collector_rings * 9
    if n_ring_accounts + 50 > n_accounts:
        raise ValueError("n_accounts is too small for the requested number of rings.")

    perm = rng.permutation(n_accounts)
    ring_pool = [accounts[i] for i in perm[:n_ring_accounts]]
    background_pool = [accounts[i] for i in perm]  # everyone can transact normally

    # Heavy-tailed activity: a few busy accounts, many quiet ones.
    activity = rng.pareto(1.6, n_accounts) + 1
    activity = activity / activity.sum()
    acct_index = {a: i for i, a in enumerate(accounts)}
    act = np.array([activity[acct_index[a]] for a in background_pool])
    act = act / act.sum()

    rows = []

    def add(sender, receiver, amount, ts, fraud=False):
        rows.append((sender, receiver, round(float(amount), 2), ts, fraud))
        return len(rows) - 1

    def business_time(day_offset):
        hour = int(np.clip(rng.normal(14, 4), 6, 22))
        return t0 + pd.Timedelta(days=int(day_offset), hours=hour, minutes=int(rng.integers(0, 60)))

    # Ordinary payments.
    senders = rng.choice(background_pool, size=n_normal, p=act)
    receivers = rng.choice(background_pool, size=n_normal, p=act)
    amounts = np.clip(rng.lognormal(mean=7.8, sigma=0.75, size=n_normal), 150, 60000)
    for s, r, a in zip(senders, receivers, amounts):
        if s == r:
            continue
        add(s, r, a, business_time(rng.integers(0, days)))

    truth, cursor = [], 0

    # Cycle rings.
    for k in range(n_cycle_rings):
        size = int(rng.integers(3, 6))
        members = ring_pool[cursor:cursor + size]
        cursor += 5  # keep pool slicing simple; unused slots stay legitimate
        base = float(rng.uniform(3500, 9000))
        start_day = int(rng.integers(3, days - 8))
        rounds = int(rng.integers(2, 4))
        tx_idx = []
        for rnd in range(rounds):
            ts = business_time(start_day + rnd * int(rng.integers(1, 3)))
            amt = base * float(rng.uniform(0.97, 1.03))
            for i in range(size):
                sender, receiver = members[i], members[(i + 1) % size]
                amt *= float(rng.uniform(0.985, 1.005))          # small "fee" leakage
                ts = ts + pd.Timedelta(minutes=int(rng.integers(20, 300)))
                tx_idx.append(add(sender, receiver, amt, ts, fraud=True))
        truth.append({"ring_id": f"GT-C{k + 1}", "type": "cycle", "accounts": members, "_tx": tx_idx})

    # Collector (mule) rings.
    for k in range(n_collector_rings):
        feeders = int(rng.integers(5, 8))
        members = ring_pool[cursor:cursor + feeders + 2]
        cursor += 9
        hub, beneficiary, feed = members[0], members[1], members[2:]
        base = float(rng.uniform(4000, 8000))
        day = int(rng.integers(3, days - 5))
        tx_idx, total = [], 0.0
        ts = business_time(day)
        for f in feed:
            amt = base * float(rng.uniform(0.92, 1.08))
            total += amt
            ts = ts + pd.Timedelta(minutes=int(rng.integers(15, 240)))
            tx_idx.append(add(f, hub, amt, ts, fraud=True))
        ts = ts + pd.Timedelta(hours=int(rng.integers(2, 10)))
        tx_idx.append(add(hub, beneficiary, total * 0.96, ts, fraud=True))
        truth.append({"ring_id": f"GT-H{k + 1}", "type": "collector",
                      "accounts": members, "_tx": tx_idx})

    # Camouflage: ring accounts also behave like everyone else.
    ring_accounts = {a for t in truth for a in t["accounts"]}
    outsiders = [a for a in accounts if a not in ring_accounts]
    for a in sorted(ring_accounts):
        for _ in range(int(rng.integers(3, 9))):
            other = str(rng.choice(outsiders))
            amount = float(np.clip(rng.lognormal(7.8, 0.75), 150, 60000))
            ts = business_time(rng.integers(0, days))
            if rng.random() < 0.5:
                add(a, other, amount, ts)
            else:
                add(other, a, amount, ts)

    df = pd.DataFrame(rows, columns=["sender", "receiver", "amount", "timestamp", "is_fraud"])
    order = df["timestamp"].argsort(kind="stable").to_numpy()
    df = df.iloc[order].reset_index()
    old_to_new = {int(old): new for new, old in enumerate(df["index"])}
    df = df.drop(columns="index")
    df.insert(0, "transaction_id", [f"TX{i:06d}" for i in range(1, len(df) + 1)])
    df["is_fraud"] = df["is_fraud"].astype(int)

    for t in truth:
        t["tx_ids"] = [f"TX{old_to_new[i] + 1:06d}" for i in t.pop("_tx")]
    return df, truth
