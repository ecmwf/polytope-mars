* Don't get GRIB header from FDB, so we don't have information required for 'parameter' section, but it is just a lookup. Can we get it direct from earthkit?


# Vertical Profile

* lat, lon and level in DOMAIN AXES with REFERENCING
* parameter metadata in PARAMETERS
* values goes in RANGES
* step could be in DOMAIN AXES as time axis (many steps in single domain)
    or single step as metadata inside DOMAIN
* in terms of interoperability with downstream applications and compact serving of data
  we should ideally use some form of time range rather than individual coverages for each time step. may switch dynamically between step (if multiple requested) and date/time (if multiple requested). priortise STEP if multiple steps exist.

# Time Series

↳root=None
	↳number=0
		↳time=2017-01-01 00:00:00
			↳step=0 nanoseconds
				↳isobaricInhPa=1.0
					↳latitude=3.0
						↳longitude=7.0
				↳isobaricInhPa=2.0
					↳latitude=3.0
						↳longitude=7.0
				↳isobaricInhPa=7.0
					↳latitude=3.0
						↳longitude=7.0
				↳isobaricInhPa=100.0
					↳latitude=3.0
						↳longitude=7.0
				↳isobaricInhPa=150.0
					↳latitude=3.0
						↳longitude=7.0
        ↳time=2017-01-01 12:00:00
                ↳step=0 nanoseconds
                    ↳isobaricInhPa=1.0
                        ↳latitude=3.0
                            ↳longitude=7.0
                    ↳isobaricInhPa=2.0
                        ↳latitude=3.0
                            ↳longitude=7.0
                    ↳isobaricInhPa=7.0
                        ↳latitude=3.0
                            ↳longitude=7.0
                    ↳isobaricInhPa=100.0
                        ↳latitude=3.0
                            ↳longitude=7.0
                    ↳isobaricInhPa=150.0
                        ↳latitude=3.0
                            ↳longitude=7.0
    ↳number=1
		↳time=2017-01-01 00:00:00
			↳step=0 nanoseconds
				↳isobaricInhPa=1.0
					↳latitude=3.0
						↳longitude=7.0
				↳isobaricInhPa=2.0
					↳latitude=3.0
						↳longitude=7.0
				↳isobaricInhPa=7.0
					↳latitude=3.0
						↳longitude=7.0
				↳isobaricInhPa=100.0
					↳latitude=3.0
						↳longitude=7.0
				↳isobaricInhPa=150.0
					↳latitude=3.0
						↳longitude=7.0
        ↳time=2017-01-01 12:00:00
                ↳step=0 nanoseconds
                    ↳isobaricInhPa=1.0
                        ↳latitude=3.0
                            ↳longitude=7.0
                    ↳isobaricInhPa=2.0
                        ↳latitude=3.0
                            ↳longitude=7.0
                    ↳isobaricInhPa=7.0
                        ↳latitude=3.0
                            ↳longitude=7.0
                    ↳isobaricInhPa=100.0
                        ↳latitude=3.0
                            ↳longitude=7.0
                    ↳isobaricInhPa=150.0
                        ↳latitude=3.0
                            ↳longitude=7.0
