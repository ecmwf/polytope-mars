# vertical profile
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "sfc",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1/to/2",
    "step": "0/to/10",
    "feature" : {
        "type" : "timeseries",
        "points" : [[-9.109280931080349, 38.78655345978706]],
        "axis": "step",
	},
}

# vertical profile
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "pl",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "203/133",
    "number" : "1",
    "step": "0",
    "levelist": "1/to/1000",
    "feature" : {
        "type" : "verticalprofile",
        "points" : [[-9.109280931080349, 38.78655345978706]],
	},
}

# polygon

request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "sfc",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step": "0",
    "feature" : {
        "type" : "polygon",
        "shape" : [[-1, 1], [-1, 0], [0, 1], [-1, 1]],
	},
}

# frame

request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "sfc",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step": "0",
    "feature" : {
        "type" : "frame",
        "inner_box" : [[0, 0], [0.2, 0.2]],
        "outer_box" : [[0.1, 0.1], [0.15, 0.15]],
	},
}

# path

request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "sfc",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step": "0",
    "feature" : {
        "type" : "path",
        "points" : [[0, 0, 0], [1, 1, 1], [2, 2, 2]],
        "padding" : 1,
	},
}

# bounding box
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "sfc",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step": "0",
    "feature" : {
        "type" : "boundingbox",
        "points" : [[0, 0], [1, 1]],
	},
}

# cyclone
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step": "0",
    "feature" : {
        "type" : "cyclone",
        "points" : [[x, y, z, t, r], [x, y, z, t, r], [x, y, z, t, r]]
	},
}

# corridor
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "sfc",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step": "0",
    "feature" : {
    "type" : "corridor",
        "points" : [[0, 0, 0], [1, 1, 1], [2, 2, 2]],
        "shape" : [[-1, 1], [-1, 0], [0, 1], [-1, 1]],
	},
}

# flight path
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "flightlevel" : "FL300",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step": "0",
    "feature" : {
        "type" : "flightpath",
        "points" : [[0, 0], [1, 1], [2, 2]],
	},
}

# geoJSON
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "sfc",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step": "0",
    "feature" : {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "coordinates": [
            -3.704532267919575,
            40.424983919509685
            ],
            "type": "Point"
        }
    }	
}

# country
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "sfc",
    "expver" : "0079", 
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step": "0",
    "feature" : {
        "type" : "country",
        "country" : "Germany",
	},
}

# extreme event
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "expver" : "0079", 
    "domain" : "g",
    "number" : "1",
    "step": "0",
    "feature" : {
        "type" : "Flood",
        "path" : [[0, 0, 0], [1, 1, 0], [2, 2, 0]],
	},
}



