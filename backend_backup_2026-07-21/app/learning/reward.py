# =====================================================
# Reward Configuration
# =====================================================

SUCCESS_REWARD = 10
FAILURE_REWARD = -5
BONUS_REWARD = 20


def calculate_reward(success: bool):
    """
    Calculate reward based on success.
    """

    if success:
        return SUCCESS_REWARD

    return FAILURE_REWARD


# =====================================================
# Helper Functions
# =====================================================

def reward_success():
    """
    Reward for a successful action.
    """
    return SUCCESS_REWARD


def reward_failure():
    """
    Penalty for a failed action.
    """
    return FAILURE_REWARD


def reward_bonus():
    """
    Bonus reward for exceptional performance.
    """
    return BONUS_REWARD


def total_reward(rewards):
    """
    Calculate total reward from a list.
    """

    return sum(rewards)


def average_reward(rewards):
    """
    Calculate average reward.
    """

    if not rewards:
        return 0

    return sum(rewards) / len(rewards)


def print_reward(success):
    """
    Display reward information.
    """

    reward = calculate_reward(success)

    print("\n========== REWARD ==========")

    if reward >= 0:
        print(f"Reward Earned : +{reward}")
    else:
        print(f"Penalty : {reward}")

    return reward