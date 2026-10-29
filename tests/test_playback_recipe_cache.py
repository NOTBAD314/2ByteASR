from twobyteasr.caption_style.style_recipe import StyleRecipe,route_recipe,_route_serialized_recipe


def test_nested_mutation_invalidates_cached_renderer_decision():
    payload=StyleRecipe(name='Routing fixture').to_dict()
    first=route_recipe(payload)
    assert first.engine=='native'
    payload['colors']['fill']={'type':'linear','stops':[{'color':'#FFFFFF','position':0},{'color':'#336699','position':1}],'angle':90}
    assert route_recipe(payload).engine=='remotion'
    payload['colors']['fill']='#FFFFFF'
    assert route_recipe(payload).engine=='native'


def test_equal_recipes_share_validation_but_not_mutable_caller_data():
    import copy
    payload=StyleRecipe(name='Cache fixture').to_dict()
    _route_serialized_recipe.cache_clear()
    a=route_recipe(payload);b=route_recipe(copy.deepcopy(payload))
    assert a==b and _route_serialized_recipe.cache_info().hits==1
    payload['engine']='remotion'
    assert route_recipe(payload).engine=='remotion'
