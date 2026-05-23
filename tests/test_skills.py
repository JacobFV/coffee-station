from coffee_station.skills import SkillLibrary


def test_skill_library_loads_packaged_robot_skills():
    library = SkillLibrary()
    names = {skill.name for skill in library.list()}

    assert "pose-table-6dof" in names
    assert "gripper-world-calibration" in names
    assert "pour-coffee-cup-to-cup" in names


def test_skill_library_auto_activates_relevant_skill():
    library = SkillLibrary()

    active = library.activate_for_text("pour coffee from one cup to another")

    assert active
    assert active[0].name == "pour-coffee-cup-to-cup"
