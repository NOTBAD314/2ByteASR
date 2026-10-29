from twobyteasr.caption_style.studio_fonts import missing_project_fonts
from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, SubtitleStyle


def test_missing_project_fonts_is_case_insensitive_and_unique():
    project = SubtitleProject(
        media=StudioMedia("video.mp4"),
        styles=[
            SubtitleStyle("default", "Default", font_family="Known Font"),
            SubtitleStyle("other", "Other", font_family="Missing Font"),
            SubtitleStyle("third", "Third", font_family="Missing Font"),
        ],
    )
    assert missing_project_fonts(project, ["known font"]) == ["Missing Font"]
