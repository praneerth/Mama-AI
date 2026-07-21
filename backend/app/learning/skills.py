from dataclasses import dataclass

# =====================================================
# Skill Model
# =====================================================

@dataclass
class Skill:

    name: str
    uses: int = 1


# =====================================================
# Skill Storage
# =====================================================

skills = []


def learn_skill(action: str):
    """
    Learn a successful action as a reusable skill.
    """

    action = action.strip().lower()

    for skill in skills:

        if skill.name == action:
            skill.uses += 1

            print(f"Updated skill: {skill.name} ({skill.uses})")
            return skill

    skill = Skill(action)

    skills.append(skill)

    print(f"New skill learned: {skill.name}")

    return skill


# =====================================================
# Helper Functions
# =====================================================

def all_skills():
    """
    Return all learned skills.
    """
    return skills


def total_skills():
    """
    Return total number of learned skills.
    """
    return len(skills)


def has_skill(action: str):
    """
    Check whether a skill exists.
    """

    action = action.strip().lower()

    for skill in skills:
        if skill.name == action:
            return True

    return False


def get_skill(action: str):
    """
    Return a learned skill.
    """

    action = action.strip().lower()

    for skill in skills:
        if skill.name == action:
            return skill

    return None


def forget_skill(action: str):
    """
    Remove a learned skill.
    """

    action = action.strip().lower()

    for skill in skills:

        if skill.name == action:
            skills.remove(skill)
            print(f"Forgot skill: {action}")
            return True

    return False


def clear_skills():
    """
    Remove all learned skills.
    """

    skills.clear()

    print("All skills cleared.")


def print_skills():
    """
    Display every learned skill.
    """

    print("\n========== LEARNED SKILLS ==========")

    if not skills:
        print("No skills learned.")
        return

    for i, skill in enumerate(skills, start=1):

        print(f"{i}. {skill.name} (used {skill.uses} times)")