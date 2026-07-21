from app.database.database import execute, fetch_one, fetch_all
from app.database.models import skill_from_row, skills_from_rows


# =====================================================
# Add Skill
# =====================================================

def add_skill(name):

    if skill_exists(name):
        return

    execute(
        """
        INSERT INTO skills(name, uses)
        VALUES(?, ?)
        """,
        (name, 1),
    )


# =====================================================
# Get Skill
# =====================================================

def get_skill(name):

    row = fetch_one(
        """
        SELECT *
        FROM skills
        WHERE name = ?
        """,
        (name,),
    )

    return skill_from_row(row)


# =====================================================
# Increase Usage
# =====================================================

def increase_usage(name):

    if not skill_exists(name):
        add_skill(name)
        return

    execute(
        """
        UPDATE skills
        SET uses = uses + 1
        WHERE name = ?
        """,
        (name,),
    )


# =====================================================
# Get All Skills
# =====================================================

def get_all_skills():

    rows = fetch_all(
        """
        SELECT *
        FROM skills
        ORDER BY uses DESC
        """
    )

    return skills_from_rows(rows)


# =====================================================
# Delete Skill
# =====================================================

def delete_skill(name):

    execute(
        """
        DELETE FROM skills
        WHERE name = ?
        """,
        (name,),
    )


# =====================================================
# Clear Skills
# =====================================================

def clear_skills():

    execute(
        """
        DELETE FROM skills
        """
    )


# =====================================================
# Count Skills
# =====================================================

def count_skills():

    row = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM skills
        """
    )

    return row["total"]


# =====================================================
# Most Used Skill
# =====================================================

def most_used_skill():

    row = fetch_one(
        """
        SELECT *
        FROM skills
        ORDER BY uses DESC
        LIMIT 1
        """
    )

    return skill_from_row(row)


# =====================================================
# Least Used Skill
# =====================================================

def least_used_skill():

    row = fetch_one(
        """
        SELECT *
        FROM skills
        ORDER BY uses ASC
        LIMIT 1
        """
    )

    return skill_from_row(row)


# =====================================================
# Reset Usage
# =====================================================

def reset_skill_usage(name):

    execute(
        """
        UPDATE skills
        SET uses = 1
        WHERE name = ?
        """,
        (name,),
    )


# =====================================================
# Helper
# =====================================================

def skill_exists(name):

    return get_skill(name) is not None