
# Take in output results from polytope feature extraction and convert to geojson points 
def convert_to_geojson(self, results):
    geojson = {"type": "FeatureCollection", "features": []}
    list_of_features = []
    param_values = [val.result for val in results.leaves]
    values = [val.get_ancestors() for val in results.leaves]
    for i, ancestor in enumerate(values):
        new_feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [102.0, 0.5]},
            "properties": {},
        }
        coords = []
        new_feature["properties"][param_values[i][0]] = param_values[i][1]
        for feature in ancestor:
            if str(feature).split("=")[0] == "latitude":
                coords.append(str(feature).split("=")[1])
            elif str(feature).split("=")[0] == "longitude":
                coords.append(str(feature).split("=")[1])
            else:
                new_feature["properties"][str(feature).split("=")[0]] = str(feature).split("=")[1]
        new_feature["geometry"]["coordinates"] = coords
        list_of_features.append(new_feature)
    geojson["features"] = list_of_features
    return geojson
