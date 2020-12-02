
rttov_run
=========================

.. container::
    
    .. container:: leftside

        .. image:: /_static/RTTOV_RUN.png
           :width: 48px

    .. container:: rightside

        This function performs the same task as the `Rttov Run <https://confluence.ecmwf.int/display/METV/rttov+run>`_ icon in Metview’s user interface. It accepts its parameters as keyword arguments, described below.


.. py:function:: rttov_run(**kwargs)
  
    Description comes here!


    :param rttov_exe_path: 
    :type rttov_exe_path: str


    :param rttov_input_data: 
    :type rttov_input_data: str


    :param rttov_input_data_path: 
    :type rttov_input_data_path: str


    :param rttov_sensor: 
    :type rttov_sensor: str, default: "iasi"


    :param rttov_channels: 
    :type rttov_channels: str


    :param rttov_channels_path: 
    :type rttov_channels_path: str


    :param rttov_coefficients: 
    :type rttov_coefficients: str


    :param rttov_coefficients_path: 
    :type rttov_coefficients_path: str


    :param rttov_satellite_zenith_angle: 
    :type rttov_satellite_zenith_angle: number, default: 0


    :param rttov_satellite_azimuth_angle: 
    :type rttov_satellite_azimuth_angle: number, default: 0


    :param rttov_solar_zenith_angle: 
    :type rttov_solar_zenith_angle: number, default: 0


    :param rttov_solar_azimuth_angle: 
    :type rttov_solar_azimuth_angle: number, default: 0


    :rtype: None
