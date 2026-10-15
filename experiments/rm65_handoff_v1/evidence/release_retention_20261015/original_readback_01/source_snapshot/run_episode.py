"""Current single episode: full table pickup -> handoff -> right placement.

Historical transfer-only/workspace runners and ledgers remain in Git unchanged;
this entry no longer starts those tasks or performs an expert initial pickup.
"""


def main():
    from full_handoff_episode import main as full_main
    return full_main()


if __name__=='__main__':main()
