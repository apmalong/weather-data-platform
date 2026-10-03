from wx.ingest.noaa import formats


def test_fixed_width_layouts_match_the_readme(readme):
    documented = formats.readme_layouts(readme)
    for dataset, columns in formats.FIXED_WIDTH.items():
        assert [(c.start, c.end) for c in columns] == [(s, e) for _, s, e in documented[dataset]], dataset


def test_element_catalog_reads_units_and_scale(readme):
    catalog = {e.code: e for e in formats.element_catalog(readme)}
    assert (catalog["TMAX"].unit, catalog["TMAX"].scale, catalog["TMAX"].core) == ("degrees C", 0.1, True)
    assert (catalog["PRCP"].unit, catalog["PRCP"].scale) == ("mm", 0.1)
    assert (catalog["SNOW"].unit, catalog["SNOW"].scale) == ("mm", 1.0)  # whole mm, unlike PRCP
    assert (catalog["WSFG"].unit, catalog["WSFG"].scale) == ("meters per second", 0.1)
    assert (catalog["WDFG"].unit, catalog["WDFG"].scale) == ("degrees", 1.0)
    assert (catalog["ASLP"].unit, catalog["ASLP"].scale) == ("hPa", 0.1)  # "hPa * 10"
    assert {"PRCP", "SNOW", "SNWD", "TMAX", "TMIN"} == {c for c, e in catalog.items() if e.core}


def test_wrapped_descriptions_are_joined(readme):
    catalog = {e.code: e for e in formats.element_catalog(readme)}
    assert catalog["ACMC"].description == (
        "Average cloudiness midnight to midnight from 30-second ceilometer data " "(percent)"
    )
    assert catalog["ACMC"].unit == "percent"
