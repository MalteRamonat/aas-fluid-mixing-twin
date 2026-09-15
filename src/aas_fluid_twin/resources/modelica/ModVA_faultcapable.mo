// ModVA_faultcapable — derived from the benchmark's ModVA_online_stable.mo by
// scripts/derive_faultcapable.py (aas-fluid-mixing-twin). Do not edit by hand.
//
// Adds the elements the recorded faults were induced with (Tee4/V211/X203, Tee3/Tee5/V210,
// V212 as a parameter) and corrects the TI261/TI262 placement (deviation D4). With the fault
// handles at their defaults the model is hydraulically the upstream model.
model ModVA_faultcapable
  //input Real Test =4;
  /*
    Documentation of Simulation Runs and changes to the model
    run 1:        according to documentation to my best knowledge
    result run 1: found that 1) B203 is filled much faster that B201 with B202 in the middle
                  This will be due to the shorter lenght of the pipes to B203 in comparison to B201
                  in reality, however it is the other way around. B201 is filled faster than B203
                  This is due to the Tee no receiving as much of the fast moving water
                  Thus is not modeled correctly in Modelica. I have adjusted this in reality by slightly closing the vavles above the tanks
                  I will try do do something similar for the simulation in run 2.
                  Hopefully I can fix this issue by installing automatic valves in the real plant
                  Another issue that I found is that P202 pumps much faster than P201 in reality.
                  This might be due to differences in pressure drops after the two pumps. I will try to ammend for this in run 2.
      
    run 2:       reduced V204.m_flow_nominal and V205.m_flow_nominal, changed N_in for P202
    result run 2:
    */
  replaceable package Medium = Modelica.Media.Water.StandardWaterOnePhase constrainedby Modelica.Media.Interfaces.PartialMedium;
  inner Modelica.Fluid.System system(dp_small = 100, energyDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial, massDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial) annotation(
    Placement(transformation(origin = {-182, 74}, extent = {{-10, -10}, {10, 10}})));
  // Tanks
  Modelica.Fluid.Examples.AST_BatchPlant.BaseClasses.TankWithTopPorts tank_B201(redeclare package Medium = Medium, V0 = 0.0001, crossArea = 0.01431355, height = 0.22, level_start = 0.15108, nPorts = 1, nTopPorts = 2, portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.011, height = 0, zeta_out = 0, zeta_in = 1)}, stiffCharacteristicForEmptyPort = false) annotation(
    Placement(visible = true, transformation(origin = {-89, 31}, extent = {{-11, -11}, {11, 11}}, rotation = 0)));
  Modelica.Fluid.Examples.AST_BatchPlant.BaseClasses.TankWithTopPorts tank_B202(redeclare package Medium = Medium, V0 = 0.0001, crossArea = 0.01431355, height = 0.22, level_start = 0.151, nPorts = 1, nTopPorts = 1, portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.011, height = 0, zeta_out = 0, zeta_in = 1)}, stiffCharacteristicForEmptyPort = false) annotation(
    Placement(visible = true, transformation(origin = {-51, 31}, extent = {{-11, -11}, {11, 11}}, rotation = 0)));
  Modelica.Fluid.Examples.AST_BatchPlant.BaseClasses.TankWithTopPorts tank_B203(redeclare package Medium = Medium, V0 = 0.0001, crossArea = 0.01431355, height = 0.22, level_start = 0.15108, nPorts = 1, nTopPorts = 1, portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.011, height = 0, zeta_out = 0, zeta_in = 1)}, stiffCharacteristicForEmptyPort = false) annotation(
    Placement(visible = true, transformation(origin = {-13, 31}, extent = {{-11, -11}, {11, 11}}, rotation = 0)));
  Modelica.Fluid.Examples.AST_BatchPlant.BaseClasses.TankWithTopPorts tank_B204(redeclare package Medium = Medium, V0 = 0.0001, crossArea = 0.0324, height = 0.35, level_start = 0.00136, nPorts = 1, nTopPorts = 1, portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.011, height = 0, zeta_out = 0, zeta_in = 1)}, stiffCharacteristicForEmptyPort = false) annotation(
    Placement(visible = true, transformation(origin = {47, 25}, extent = {{-11, -11}, {11, 11}}, rotation = 0)));
  /*                       
                  Modelica.Fluid.Vessels.OpenTank tank_B201(redeclare package Medium = Medium, T_start = Modelica.Units.Conversions.from_degC(20), crossArea = 0.01431355, height = 0.22, level_start = 0.2, nPorts = 0, portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.01, height = 0.22, zeta_out = 0, zeta_in = 1), Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.01, height = 0.000001, zeta_out = 0, zeta_in = 1)}, use_portsData = true) annotation(
                    Placement(visible = true, transformation(origin = {-88, 28}, extent = {{-12, -12}, {12, 12}}, rotation = 0)));
                   
                  Modelica.Fluid.Vessels.OpenTank tank_B202(redeclare package Medium = Medium, T_start = Modelica.Units.Conversions.from_degC(20), crossArea = 0.01431355, height = 0.22, level_start = 0.2, nPorts = 0, portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.01, height = 0.22, zeta_out = 0, zeta_in = 1), Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.01, height = 0.000001, zeta_out = 0, zeta_in = 1)}, use_portsData = true) annotation(
                    Placement(visible = true, transformation(origin = {-50, 28}, extent = {{-12, -12}, {12, 12}}, rotation = 0)));
                  Modelica.Fluid.Vessels.OpenTank tank_B203(redeclare package Medium = Medium, T_start = Modelica.Units.Conversions.from_degC(20), crossArea = 0.01431355, height = 0.22, level_start = 0.2, nPorts = 0, portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.01, height = 0.22, zeta_out = 0, zeta_in = 1), Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.01, height = 0.000001, zeta_out = 0, zeta_in = 1)}, use_portsData = true) annotation(
                    Placement(visible = true, transformation(origin = {-14, 28}, extent = {{-12, -12}, {12, 12}}, rotation = 0)));
                  Modelica.Fluid.Vessels.OpenTank tank_B204(redeclare package Medium = Medium, T_start = Modelica.Units.Conversions.from_degC(20), crossArea = 0.0324, height = 0.35, level_start = 0.01, nPorts = 0, portsData = {Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.01, height = 0.34, zeta_out = 0, zeta_in = 1), Modelica.Fluid.Vessels.BaseClasses.VesselPortsData(diameter = 0.01, height = 0.000001, zeta_out = 0, zeta_in = 1)}, use_portsData = true) annotation(
                    Placement(visible = true, transformation(origin = {46, 26}, extent = {{-14, -14}, {14, 14}}, rotation = 0)));
                */
  //Actuators
  //Valves
  Modelica.Fluid.Valves.ValveLinear V201(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0) annotation(
    Placement(visible = true, transformation(origin = {-88, -12}, extent = {{6, -6}, {-6, 6}}, rotation = 90)));
  Modelica.Fluid.Valves.ValveLinear V202(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0) annotation(
    Placement(visible = true, transformation(origin = {-50, -10}, extent = {{6, -6}, {-6, 6}}, rotation = 90)));
  Modelica.Fluid.Valves.ValveLinear V203(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0) annotation(
    Placement(transformation(origin = {-14, -8}, extent = {{6, -6}, {-6, 6}}, rotation = 90)));
  Modelica.Fluid.Valves.ValveLinear V204(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0) annotation(
    Placement(transformation(origin = {-88, 70}, extent = {{6, -6}, {-6, 6}}, rotation = 90)));
  Modelica.Fluid.Valves.ValveLinear V205(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0) annotation(
    Placement(transformation(origin = {-50, 68}, extent = {{6, -6}, {-6, 6}}, rotation = 90)));
  Modelica.Fluid.Valves.ValveLinear V206(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0) annotation(
    Placement(transformation(origin = {-14, 66}, extent = {{6, -6}, {-6, 6}}, rotation = 90)));
  Modelica.Fluid.Valves.ValveLinear V212(redeclare package Medium = Medium, dp_nominal = 2000, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0) annotation(
    Placement(transformation(origin = {46, -16}, extent = {{6, 6}, {-6, -6}}, rotation = 90)));
  Modelica.Fluid.Valves.ValveLinear V209(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0) annotation(
    Placement(visible = true, transformation(origin = {120, -10}, extent = {{-6, -6}, {6, 6}}, rotation = 0)));
  //Pumps
  Modelica.Fluid.Machines.PrescribedPump P201(redeclare package Medium = Medium, N_nominal = 166.43, m_flow_start = 0.000001, T_start = system.T_start, V(displayUnit = "m3") = 0.00004398128, checkValve = true, checkValveHomotopy = Modelica.Fluid.Types.CheckValveHomotopyType.Closed, energyDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial, redeclare function flowCharacteristic = Modelica.Fluid.Machines.BaseClasses.PumpCharacteristics.quadraticFlow(V_flow_nominal = {P201_V_flow_at_max_head, P201_V_flow_at_middle_head, P201_V_flow_at_min_head}, head_nominal = {P201_head_max, P201_head_middle, P201_head_min}), massDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial, nParallel = 1, p_a_start = 100000, p_b_start = 100000, use_N_in = true) annotation(
    Placement(visible = true, transformation(origin = {-9, -55}, extent = {{-7, -7}, {7, 7}}, rotation = 0)));
  Modelica.Fluid.Machines.PrescribedPump P202(redeclare package Medium = Medium, N_nominal = 166.43, m_flow_start = 0.000001, T_start = system.T_start, V(displayUnit = "m3") = 0.00004398128, checkValve = true, checkValveHomotopy = Modelica.Fluid.Types.CheckValveHomotopyType.Closed, energyDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial, redeclare function flowCharacteristic = Modelica.Fluid.Machines.BaseClasses.PumpCharacteristics.quadraticFlow(V_flow_nominal = {P202_V_flow_at_max_head, P202_V_flow_at_middle_head, P202_V_flow_at_min_head}, head_nominal = {P202_head_max, P202_head_middle, P202_head_min}), massDynamics = Modelica.Fluid.Types.Dynamics.FixedInitial, nParallel = 1, p_a_start = 100000, p_b_start = 100000, use_N_in = true) annotation(
    Placement(transformation(origin = {65, -45}, extent = {{-7, -7}, {7, 7}})));
  //Sensors
  //Pipes
  Modelica.Fluid.Pipes.StaticPipe pipe_V206_B201(redeclare package Medium = Medium, diameter = 0.01, height_ab = -0.05, length = 0.15) annotation(
    Placement(transformation(origin = {-88, 51}, extent = {{5, -5}, {-5, 5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_V205_B202(redeclare package Medium = Medium, diameter = 0.01, height_ab = -0.05, length = 0.15) annotation(
    Placement(transformation(origin = {-50, 51}, extent = {{5, -5}, {-5, 5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_V204_B203(redeclare package Medium = Medium, diameter = 0.01, height_ab = -0.05, length = 0.15) annotation(
    Placement(transformation(origin = {-14, 51}, extent = {{5, -5}, {-5, 5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_B201_V201(redeclare package Medium = Medium, diameter = 0.01, height_ab = -0.04, length = 0.27) annotation(
    Placement(visible = true, transformation(origin = {-88, 5}, extent = {{5, -5}, {-5, 5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_B202_V202(redeclare package Medium = Medium, diameter = 0.01, height_ab = -0.04, length = 0.27) annotation(
    Placement(visible = true, transformation(origin = {-50, 5}, extent = {{5, -5}, {-5, 5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_B203_V203(redeclare package Medium = Medium, diameter = 0.01, height_ab = -0.04, length = 0.27) annotation(
    Placement(transformation(origin = {-14, 5}, extent = {{5, -5}, {-5, 5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_V201_Tee1(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.19) annotation(
    Placement(visible = true, transformation(origin = {-76, -36}, extent = {{-6, -6}, {6, 6}}, rotation = 0)));
  Modelica.Fluid.Pipes.StaticPipe pipe_V202_Tee2(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.11) annotation(
    Placement(visible = true, transformation(origin = {-43, -19}, extent = {{-5, -5}, {5, 5}}, rotation = 0)));
  // pipe_V203_Tee2 is replaced by pipe_V203_Tee3 + Tee3 + pipe_Tee3_Tee2
  /* Modelica.Fluid.Pipes.StaticPipe pipe_V203_Tee2(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.31) annotation(
    Placement(visible = true, transformation(origin = {-19, -19}, extent = {{5, -5}, {-5, 5}}, rotation = 0))); */
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee2_Tee1(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.11) annotation(
    Placement(visible = true, transformation(origin = {-47, -29}, extent = {{5, -5}, {-5, 5}}, rotation = 0)));
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee1_P201(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.16) annotation(
    Placement(visible = true, transformation(origin = {-37, -55}, extent = {{-5, -5}, {5, 5}}, rotation = 0)));
  Modelica.Fluid.Pipes.StaticPipe Pipe_V207_P202(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.23) annotation(
    Placement(transformation(origin = {45, -35}, extent = {{5, 5}, {-5, -5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_P202_Tee6(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0.1, length = 0.1) annotation(
    Placement(transformation(origin = {83, -45}, extent = {{-5, 5}, {5, -5}})));
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee6_V207(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0.09, length = 0.09) annotation(
    Placement(transformation(origin = {102, -10}, extent = {{-6, 6}, {6, -6}})));
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee6_FI272(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0.20, length = 0.50) annotation(
    Placement(visible = true, transformation(origin = {87, 49}, extent = {{-5, 5}, {5, -5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee8_V206(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.26) annotation(
    Placement(visible = true, transformation(origin = {-15, 85}, extent = {{5, -5}, {-5, 5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee8_V205(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.06) annotation(
    Placement(visible = true, transformation(origin = {-49, 85}, extent = {{5, 5}, {-5, -5}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee7_V206(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.15) annotation(
    Placement(transformation(origin = {-89, 87}, extent = {{5, 5}, {-5, -5}}, rotation = 90)));
  // Fittings
  //Tees
  Modelica.Fluid.Fittings.TeeJunctionVolume Tee1(redeclare package Medium = Medium, V = 0.0000003) annotation(
    Placement(visible = true, transformation(origin = {-59, -45}, extent = {{5, -5}, {-5, 5}}, rotation = 90)));
  Modelica.Fluid.Fittings.TeeJunctionVolume Tee6(redeclare package Medium = Medium, V = 0.0000003) annotation(
    Placement(visible = true, transformation(origin = {87, -9}, extent = {{-5, 5}, {5, -5}}, rotation = 90)));
  Modelica.Fluid.Fittings.TeeJunctionVolume Tee2(redeclare package Medium = Medium, V = 0.0000003) annotation(
    Placement(visible = true, transformation(origin = {-31, -23}, extent = {{-5, -5}, {5, 5}}, rotation = -90)));
  Modelica.Fluid.Fittings.TeeJunctionVolume Tee8(redeclare package Medium = Medium, V = 0.0000003) annotation(
    Placement(visible = true, transformation(origin = {-49, 99}, extent = {{5, 5}, {-5, -5}}, rotation = 0)));
  //Boundaries
  Modelica.Fluid.Sources.FixedBoundary boundary(redeclare package Medium = Medium, nPorts = 1) annotation(
    Placement(visible = true, transformation(origin = {142, -18}, extent = {{10, -10}, {-10, 10}}, rotation = 0)));
  //Signals
  //Pump Characteristics
  parameter Real P201_V_flow_at_max_head = 0.000122;
  //[0.0001, 0.00015]
  parameter Real P201_V_flow_at_middle_head = 0.0002;
  //[0.00018, 0.00021]
  parameter Real P201_V_flow_at_min_head = 0.00025;
  //[0.00022, 0.00028]
  parameter Real P201_head_max = 2.045;
  //[1.85, 2.20]     (Viel Förderhöhe sorgt für wenig Durchfluss)
  parameter Real P201_head_middle = 1.534;
  //[1.35, 1.649]
  parameter Real P201_head_min = 1.022;
  //[0.85, 1.149]
  parameter Real P202_V_flow_at_max_head = 0.000122;
  //[0.0001, 0.00015]
  parameter Real P202_V_flow_at_middle_head = 0.0002;
  //[0.00018, 0.00021]
  parameter Real P202_V_flow_at_min_head = 0.00025;
  //[0.00022, 0.00028]
  parameter Real P202_head_max = 2.045;
  //[1.85, 2.20]     (Viel Förderhöhe sorgt für wenig Durchfluss)
  parameter Real P202_head_middle = 1.534;
  //[1.35, 1.649]
  parameter Real P202_head_min = 1.022;
  //[0.85, 1.149]
  //Control
  //State Graph
  // Cut to reduce compilation time
  /*
                      Modelica.Blocks.Sources.RealExpression B201_level(y = tank_B201.level) annotation(
                        Placement(visible = true, transformation(origin = {-376, 34}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.RealExpression B202_level(y = tank_B202.level) annotation(
                        Placement(visible = true, transformation(origin = {-378, -2}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.RealExpression B203_level(y = tank_B203.level) annotation(
                        Placement(visible = true, transformation(origin = {-378, -48}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.RealExpression B204_level(y = tank_B204.level) annotation(
                        Placement(visible = true, transformation(origin = {-378, -96}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.BooleanExpression LA210(y = if tank_B201.level > 0.219 then true else false) annotation(
                        Placement(visible = true, transformation(origin = {-350, 42}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.BooleanExpression LS202(y = if tank_B201.level < 0.01 then true else false) annotation(
                        Placement(visible = true, transformation(origin = {-350, 28}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.BooleanExpression LA211(y = if tank_B202.level > 0.219 then true else false) annotation(
                        Placement(visible = true, transformation(origin = {-350, 6}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.BooleanExpression LS203(y = if tank_B202.level < 0.01 then true else false) annotation(
                        Placement(visible = true, transformation(origin = {-350, -10}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.BooleanExpression LA212(y = if tank_B203.level > 0.219 then true else false) annotation(
                        Placement(visible = true, transformation(origin = {-350, -42}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.BooleanExpression LS204(y = if tank_B203.level < 0.01 then true else false) annotation(
                        Placement(visible = true, transformation(origin = {-350, -56}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.BooleanExpression LA213(y = if tank_B204.level > 0.349 then true else false) annotation(
                        Placement(visible = true, transformation(origin = {-350, -80}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.BooleanExpression LS205(y = if tank_B204.level > 0.175 then true else false) annotation(
                        Placement(visible = true, transformation(origin = {-350, -96}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                      Modelica.Blocks.Sources.BooleanExpression LS206(y = if tank_B204.level < 0.01 then true else false) annotation(
                        Placement(visible = true, transformation(origin = {-350, -110}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
                     */
  Modelica.Blocks.Continuous.FirstOrder P201_Characteristic(T = 1, k = 100) annotation(
    Placement(visible = true, transformation(origin = {-90, -70}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
  Modelica.Blocks.Continuous.FirstOrder P202_Characteristic(T = 1, k = 100) annotation(
    Placement(visible = true, transformation(origin = {46, -70}, extent = {{-10, -10}, {10, 10}}, rotation = 0)));
  Modelica.Blocks.Sources.CombiTimeTable ActuatorControl(table = [0.666854, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0; 9.814724, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 36.58265, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 61.005047, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 63.436195, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 87.566434, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0; 90.038029, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0; 117.746421, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0; 145.552872, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0; 172.382396, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0; 173.98046, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 199.040477, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 226.016638, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 251.662394, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0; 278.878051, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0; 305.968482, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0; 335.499928, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0; 337.132809, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 361.863531, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 388.631872, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 414.924363, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0; 442.347847, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0; 470.993791, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0; 498.149002, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0; 499.896796, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 527.467523, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 553.483404, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0; 578.807363, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0; 580.653431, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0; 600.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0], timeEvents = Modelica.Blocks.Types.TimeEvents.NoTimeEvents, smoothness = Modelica.Blocks.Types.Smoothness.ConstantSegments) annotation(
    Placement(transformation(origin = {-180, -6}, extent = {{-10, -10}, {10, 10}})));
  Modelica.Fluid.Pipes.StaticPipe Pipe_B204_V207(redeclare package Medium = Medium, diameter = 0.01, height_ab = -0.006, length = 0.21) annotation(
    Placement(transformation(origin = {47, 3}, extent = {{5, 5}, {-5, -5}}, rotation = 90)));
  Modelica.Fluid.Sensors.VolumeFlowRate FI272(redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {51, 107}, extent = {{-5, -5}, {5, 5}}, rotation = 180)));
  Modelica.Fluid.Fittings.TeeJunctionVolume Tee7(V = 0.0000003, redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {-81, 99}, extent = {{-5, -5}, {5, 5}})));
  Modelica.Fluid.Pipes.StaticPipe Pipe_Tee7_Tee8(length = 0.12, diameter = 0.01, redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {-65, 99}, extent = {{-5, -5}, {5, 5}})));
  Modelica.Fluid.Pipes.StaticPipe Pipe_FI272_Tee7(length = 0.36, diameter = 0.01, height_ab = 0.13, redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {-11, 107}, extent = {{-5, -5}, {5, 5}}, rotation = 180)));
  Modelica.Fluid.Sensors.Pressure PI252(redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {-63, 5}, extent = {{-5, -5}, {5, 5}})));
  Modelica.Fluid.Sensors.Pressure PI251(redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {-103, 5}, extent = {{-5, -5}, {5, 5}})));
  Modelica.Fluid.Sensors.Pressure PI253(redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {-27, 5}, extent = {{-5, -5}, {5, 5}})));
  Modelica.Fluid.Sensors.Temperature TI262(redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {-14, -36}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Fluid.Sensors.Pressure PI254(redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {69, 5}, extent = {{-5, -5}, {5, 5}})));
  Modelica.Blocks.Sources.RealExpression LI211(y = tank_B201.level) annotation(
    Placement(transformation(origin = {-104, 40}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Sources.RealExpression LI212(y = tank_B202.level) annotation(
    Placement(transformation(origin = {-66, 40}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Sources.RealExpression LI213(y = tank_B203.level) annotation(
    Placement(transformation(origin = {-28, 40}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Sources.RealExpression LI214(y = tank_B204.level) annotation(
    Placement(transformation(origin = {32, 34}, extent = {{-4, -4}, {4, 4}})));
  //Modelica.Blocks.Sources.RealExpression TI261(y = tank_B204.temperature)  annotation(
  //Placement(transformation(origin = {62, 18}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Math.RealToBoolean LA205_RB(threshold = 0.175) annotation(
    Placement(transformation(origin = {104, 26}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Math.RealToBoolean LA204_RB(threshold = 0.05) annotation(
    Placement(transformation(origin = {104, 16}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Interaction.Show.BooleanValue LA205 annotation(
    Placement(transformation(origin = {118, 26}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Interaction.Show.BooleanValue LA204 annotation(
    Placement(transformation(origin = {118, 16}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Math.RealToBoolean LA240_RB(threshold = 0.3) annotation(
    Placement(transformation(origin = {104, 36}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Interaction.Show.BooleanValue LA240 annotation(
    Placement(transformation(origin = {118, 36}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Blocks.Math.RealToBoolean LA210_RB(threshold = 0.2) annotation(
    Placement(transformation(origin = {-73, 33}, extent = {{-3, -3}, {3, 3}})));
  Modelica.Blocks.Interaction.Show.BooleanValue LA210 annotation(
    Placement(transformation(origin = {-64, 34}, extent = {{-2, -2}, {2, 2}})));
  Modelica.Blocks.Math.RealToBoolean LA201_RB(threshold = 0.001) annotation(
    Placement(transformation(origin = {-73, 23}, extent = {{-3, -3}, {3, 3}})));
  Modelica.Blocks.Interaction.Show.BooleanValue LA201 annotation(
    Placement(transformation(origin = {-64, 24}, extent = {{-2, -2}, {2, 2}})));
  Modelica.Blocks.Math.RealToBoolean LA220_RB(threshold = 0.2) annotation(
    Placement(transformation(origin = {-35, 33}, extent = {{-3, -3}, {3, 3}})));
  Modelica.Blocks.Math.RealToBoolean LA202_RB(threshold = 0.001) annotation(
    Placement(transformation(origin = {-35, 23}, extent = {{-3, -3}, {3, 3}})));
  Modelica.Blocks.Math.RealToBoolean LA230_RB(threshold = 0.2) annotation(
    Placement(transformation(origin = {3, 33}, extent = {{-3, -3}, {3, 3}})));
  Modelica.Blocks.Math.RealToBoolean LA203_RB(threshold = 0.001) annotation(
    Placement(transformation(origin = {3, 23}, extent = {{-3, -3}, {3, 3}})));
  Modelica.Blocks.Interaction.Show.BooleanValue LA220 annotation(
    Placement(transformation(origin = {-26, 34}, extent = {{-2, -2}, {2, 2}})));
  Modelica.Blocks.Interaction.Show.BooleanValue LA202 annotation(
    Placement(transformation(origin = {-26, 24}, extent = {{-2, -2}, {2, 2}})));
  Modelica.Blocks.Interaction.Show.BooleanValue LA230 annotation(
    Placement(transformation(origin = {14, 34}, extent = {{-2, -2}, {2, 2}})));
  Modelica.Blocks.Interaction.Show.BooleanValue LA203 annotation(
    Placement(transformation(origin = {14, 24}, extent = {{-2, -2}, {2, 2}})));
  Modelica.Fluid.Sensors.Temperature TI261(redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {70, 18}, extent = {{-4, -4}, {4, 4}})));
  Modelica.Fluid.Sensors.VolumeFlowRate FI271(redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {13, -27}, extent = {{-7, -7}, {7, 7}}, rotation = 90)));
  Modelica.Fluid.Pipes.StaticPipe pipe_P201_FI271(redeclare package Medium = Medium, length = 0.05, diameter = 0.01, height_ab = 0.05) annotation(
    Placement(transformation(origin = {13, -45}, extent = {{-5, -5}, {5, 5}}, rotation = 90)));
  // pipe_FI271_B204 is replaced by pipe_FI271_Tee4 + Tee4 + pipe_Tee4_B204
  /* Modelica.Fluid.Pipes.StaticPipe pipe_FI271_B204(length = 0.57, diameter = 0.01, height_ab = 0.405, redeclare package Medium = Medium) annotation(
    Placement(transformation(origin = {14, 0}, extent = {{-6, -6}, {6, 6}}, rotation = 90))); */
  // --- Clogging handle (ModVA_faultcapable) ------------------------------------------------
  parameter Real V212_opening(min = 0, max = 1) = 1 "Throttle between B204 and P202 (the clogging rig); below 1 reproduces clogging";
  // --- Leak path and its two destinations (ModVA_faultcapable) -----------------------------
  parameter Real V211_opening(min = 0, max = 1) = 0 "Leak valve Tee4 -> X203; above 0 reproduces leakage";
  parameter Boolean V211_return_to_B201 = false "Reconfiguration A: route the V211 discharge into B201 instead of X203";
  parameter Real Tee4_position(min = 0.05, max = 0.95) = 0.5 "Assumed: where Tee4 sits along the FI271 -> B204 riser, as a fraction of its length";
  parameter Modelica.Units.SI.PressureDifference V211_dp_nominal = 20000 "Assumed: the leak valve is a needle valve, so it drops far more than a process valve (20 Pa) at the same flow";
  Modelica.Fluid.Fittings.TeeJunctionVolume Tee4(redeclare package Medium = Medium, V = 0.0000003);
  Modelica.Fluid.Pipes.StaticPipe pipe_FI271_Tee4(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0.405 * Tee4_position, length = 0.57 * Tee4_position);
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee4_B204(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0.405 * (1 - Tee4_position), length = 0.57 * (1 - Tee4_position));
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee4_V211(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.1);
  Modelica.Fluid.Valves.ValveLinear V211(redeclare package Medium = Medium, dp_nominal = V211_dp_nominal, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0);
  Modelica.Fluid.Fittings.TeeJunctionVolume Junction_V211(redeclare package Medium = Medium, V = 0.0000003);
  Modelica.Fluid.Valves.ValveLinear V211_to_X203(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0);
  Modelica.Fluid.Valves.ValveLinear V211_to_B201(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0);
  Modelica.Fluid.Pipes.StaticPipe pipe_V211_B201(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.5);
  Modelica.Fluid.Sources.FixedBoundary X203(redeclare package Medium = Medium, nPorts = 1);
  // --- V210 crossover (ModVA_faultcapable) -------------------------------------------------
  parameter Real V210_opening(min = 0, max = 1) = 0 "Crossover Tee3 <-> Tee5; above 0 reproduces reconfiguration B";
  parameter Modelica.Units.SI.Length crossover_length = 0.3 "Assumed: pipe length of the Tee3 -> V210 -> Tee5 crossover";
  parameter Modelica.Units.SI.Length crossover_stub_length = 0.115 "Assumed: pipe length from Tee5 to the V212 throttle";
  Modelica.Fluid.Fittings.TeeJunctionVolume Tee3(redeclare package Medium = Medium, V = 0.0000003);
  Modelica.Fluid.Pipes.StaticPipe pipe_V203_Tee3(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.155);
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee3_Tee2(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = 0.155);
  Modelica.Fluid.Fittings.TeeJunctionVolume Tee5(redeclare package Medium = Medium, V = 0.0000003);
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee5_V212(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = crossover_stub_length);
  Modelica.Fluid.Pipes.StaticPipe pipe_Tee3_V210(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = crossover_length / 2);
  Modelica.Fluid.Valves.ValveLinear V210(redeclare package Medium = Medium, dp_nominal = 20, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, m_flow_start = 0);
  Modelica.Fluid.Pipes.StaticPipe pipe_V210_Tee5(redeclare package Medium = Medium, diameter = 0.01, height_ab = 0, length = crossover_length / 2);
equation
  V210.opening = V210_opening;
  V211.opening = V211_opening;
  V211_to_X203.opening = if V211_return_to_B201 then 0 else 1;
  V211_to_B201.opening = if V211_return_to_B201 then 1 else 0;
//Control_V201.y = if time < 5 then true else false;
  V212.opening = V212_opening;
//V209.opening = 0.00000001;
/*
  B204_empty.condition = if tank_B201.level > 0.219 or tank_B202.level > 0.219 or tank_B203.level > 0.219 or tank_B204.level < 0.01 then true else false;
  V201.opening = if Empty_B201.active then 1 else 0;
  V202.opening = if Empty_B202.active then 1 else 0;
  V203.opening = if Empty_B203.active then 1 else 0;
  V204.opening = if Empty_B204.active then 1 else 0;
  V205.opening = if Empty_B204.active then 1 else 0;
  V206.opening = if Empty_B204.active then 1 else 0;
  V207.opening = if Empty_B204.active then 1 else 0;
  V209.opening = 0;
  P201.N_in = if Empty_B201.active or Empty_B202.active or Empty_B203.active then 166.43 else 0.0000001;
  P202.N_in = if Empty_B204.active then 166.43 else 0.0000001;
  */
  connect(Pipe_V207_P202.port_b, P202.port_a) annotation(
    Line(points = {{45, -40}, {45, -45}, {58, -45}}, color = {0, 127, 255}));
  connect(pipe_P202_Tee6.port_a, P202.port_b) annotation(
    Line(points = {{78, -45}, {72, -45}}, color = {0, 127, 255}));
  connect(pipe_V202_Tee2.port_b, Tee2.port_1) annotation(
    Line(points = {{-38, -18}, {-30, -18}}, color = {0, 127, 255}));
  connect(Tee2.port_2, pipe_Tee2_Tee1.port_a) annotation(
    Line(points = {{-30, -28}, {-42, -28}}, color = {0, 127, 255}));
  connect(pipe_V201_Tee1.port_b, Tee1.port_3) annotation(
    Line(points = {{-70, -36}, {-64, -36}, {-64, -44}}, color = {0, 127, 255}));
  connect(Tee1.port_1, pipe_Tee2_Tee1.port_b) annotation(
    Line(points = {{-58, -40}, {-58, -28}, {-52, -28}}, color = {0, 127, 255}));
  connect(Tee1.port_2, pipe_Tee1_P201.port_a) annotation(
    Line(points = {{-58, -50}, {-60, -50}, {-60, -54}, {-42, -54}}, color = {0, 127, 255}));
  connect(pipe_Tee1_P201.port_b, P201.port_a) annotation(
    Line(points = {{-32, -54}, {-16, -54}}, color = {0, 127, 255}));
  connect(pipe_P202_Tee6.port_b, Tee6.port_1) annotation(
    Line(points = {{88, -45}, {88, -14}}, color = {0, 127, 255}));
  connect(Tee6.port_3, pipe_Tee6_V207.port_a) annotation(
    Line(points = {{92, -8}, {93, -8}, {93, -10}, {96, -10}}, color = {0, 127, 255}));
  connect(Tee8.port_3, pipe_Tee8_V205.port_a) annotation(
    Line(points = {{-48, 94}, {-48, 90}}));
  connect(pipe_V206_B201.port_b, tank_B201.topPorts[1]) annotation(
    Line(points = {{-88, 46}, {-88, 42}}, color = {0, 127, 255}));
  connect(tank_B201.ports[1], pipe_B201_V201.port_a) annotation(
    Line(points = {{-88, 20}, {-88, 10}}, color = {0, 127, 255}));
  connect(pipe_V205_B202.port_b, tank_B202.topPorts[1]) annotation(
    Line(points = {{-50, 46}, {-50, 42}}, color = {0, 127, 255}));
  connect(tank_B202.ports[1], pipe_B202_V202.port_a) annotation(
    Line(points = {{-50, 20}, {-50, 10}}, color = {0, 127, 255}));
  connect(tank_B203.topPorts[1], pipe_V204_B203.port_b) annotation(
    Line(points = {{-12, 42}, {-14, 42}, {-14, 46}}, color = {0, 127, 255}));
  connect(tank_B203.ports[1], pipe_B203_V203.port_a) annotation(
    Line(points = {{-12, 20}, {-14, 20}, {-14, 10}}, color = {0, 127, 255}));
  connect(V209.port_a, pipe_Tee6_V207.port_b) annotation(
    Line(points = {{114, -10}, {108, -10}}));
  connect(V209.port_b, boundary.ports[1]) annotation(
    Line(points = {{126, -10}, {132, -10}, {132, -18}}, color = {0, 127, 255}));
  connect(V201.port_a, pipe_B201_V201.port_b) annotation(
    Line(points = {{-88, -6}, {-88, 0}}, color = {0, 127, 255}));
  connect(V201.port_b, pipe_V201_Tee1.port_a) annotation(
    Line(points = {{-88, -18}, {-88, -36}, {-82, -36}}, color = {0, 127, 255}));
  connect(V202.port_a, pipe_B202_V202.port_b) annotation(
    Line(points = {{-50, -4}, {-50, 0}}, color = {0, 127, 255}));
  connect(V202.port_b, pipe_V202_Tee2.port_a) annotation(
    Line(points = {{-50, -16}, {-50, -18}, {-48, -18}}, color = {0, 127, 255}));
  connect(V203.port_a, pipe_B203_V203.port_b) annotation(
    Line(points = {{-14, -2}, {-14, 0}}, color = {0, 127, 255}));
  connect(P201_Characteristic.y, P201.N_in) annotation(
    Line(points = {{-78, -70}, {-78, -59}, {-44, -59}, {-44, -60}, {-25.5, -60}, {-25.5, -48}, {-9, -48}}, color = {0, 0, 127}));
  connect(P202_Characteristic.y, P202.N_in) annotation(
    Line(points = {{58, -70}, {58, -38}, {65, -38}}, color = {0, 0, 127}));
  connect(V205.port_a, pipe_Tee8_V205.port_b) annotation(
    Line(points = {{-50, 74}, {-50, 78}, {-48, 78}, {-48, 80}}, color = {0, 127, 255}));
  connect(V205.port_b, pipe_V205_B202.port_a) annotation(
    Line(points = {{-50, 62}, {-50, 56}}, color = {0, 127, 255}));
  connect(pipe_Tee8_V206.port_b, V206.port_a) annotation(
    Line(points = {{-14, 80}, {-14, 72}}, color = {0, 127, 255}));
  connect(V206.port_b, pipe_V204_B203.port_a) annotation(
    Line(points = {{-14, 60}, {-14, 56}}, color = {0, 127, 255}));
  connect(V204.port_b, pipe_V206_B201.port_a) annotation(
    Line(points = {{-88, 64}, {-88, 56}}, color = {0, 127, 255}));
  connect(V212.port_b, Pipe_V207_P202.port_a) annotation(
    Line(points = {{46, -22}, {46, -30}}, color = {0, 127, 255}));
  connect(tank_B204.ports[1], Pipe_B204_V207.port_a) annotation(
    Line(points = {{48, 14}, {48, 8}}, color = {0, 127, 255}));
  connect(Tee6.port_2, pipe_Tee6_FI272.port_a) annotation(
    Line(points = {{88, -4}, {88, 44}}, color = {0, 127, 255}));
  connect(pipe_Tee6_FI272.port_b, FI272.port_a) annotation(
    Line(points = {{88, 54}, {84, 54}, {84, 108}, {56, 108}}, color = {0, 127, 255}));
  connect(FI272.port_b, Pipe_FI272_Tee7.port_a) annotation(
    Line(points = {{46, 108}, {-6, 108}}, color = {0, 127, 255}));
  connect(Pipe_FI272_Tee7.port_b, Tee7.port_3) annotation(
    Line(points = {{-16, 108}, {-80, 108}, {-80, 104}}, color = {0, 127, 255}));
  connect(Tee7.port_1, pipe_Tee7_V206.port_a) annotation(
    Line(points = {{-86, 100}, {-88, 100}, {-88, 92}}, color = {0, 127, 255}));
  connect(pipe_Tee7_V206.port_b, V204.port_a) annotation(
    Line(points = {{-88, 82}, {-88, 76}}, color = {0, 127, 255}));
  connect(Tee7.port_2, Pipe_Tee7_Tee8.port_a) annotation(
    Line(points = {{-76, 100}, {-70, 100}}, color = {0, 127, 255}));
  connect(Pipe_Tee7_Tee8.port_b, Tee8.port_2) annotation(
    Line(points = {{-60, 100}, {-54, 100}}, color = {0, 127, 255}));
  connect(Tee8.port_1, pipe_Tee8_V206.port_a) annotation(
    Line(points = {{-44, 100}, {-14, 100}, {-14, 90}}, color = {0, 127, 255}));
  connect(PI253.port, pipe_B203_V203.port_b) annotation(
    Line(points = {{-26, 0}, {-14, 0}}, color = {0, 127, 255}));
  connect(PI252.port, pipe_B202_V202.port_b) annotation(
    Line(points = {{-62, 0}, {-50, 0}}, color = {0, 127, 255}));
  connect(PI251.port, pipe_B201_V201.port_b) annotation(
    Line(points = {{-102, 0}, {-88, 0}}, color = {0, 127, 255}));
  connect(TI261.port, pipe_Tee3_Tee2.port_b) annotation(
    Line(points = {{-14, -40}, {-24, -40}, {-24, -18}}, color = {0, 127, 255}));
  connect(PI254.port, Pipe_B204_V207.port_b) annotation(
    Line(points = {{70, 0}, {60, 0}, {60, -2}, {48, -2}}, color = {0, 127, 255}));
  connect(LA205_RB.u, LI214.y) annotation(
    Line(points = {{99, 26}, {67.5, 26}, {67.5, 34}, {36, 34}}, color = {0, 0, 127}));
  connect(LA204_RB.u, LI214.y) annotation(
    Line(points = {{100, 16}, {92, 16}, {92, 34}, {36, 34}}, color = {0, 0, 127}));
  connect(LA205_RB.y, LA205.activePort) annotation(
    Line(points = {{108, 26}, {113, 26}}, color = {255, 0, 255}));
  connect(LA204_RB.y, LA204.activePort) annotation(
    Line(points = {{108, 16}, {114, 16}}, color = {255, 0, 255}));
  connect(LA240_RB.y, LA240.activePort) annotation(
    Line(points = {{108, 36}, {114, 36}}, color = {255, 0, 255}));
  connect(LA240_RB.u, LI214.y) annotation(
    Line(points = {{100, 36}, {92, 36}, {92, 34}, {36, 34}}, color = {0, 0, 127}));
  connect(LA210_RB.u, LI211.y) annotation(
    Line(points = {{-76, 34}, {-100, 34}, {-100, 40}}, color = {0, 0, 127}));
  connect(LA210.activePort, LA210_RB.y) annotation(
    Line(points = {{-66, 34}, {-70, 34}}, color = {255, 0, 255}));
  connect(LA201_RB.u, LI211.y) annotation(
    Line(points = {{-76, 24}, {-100, 24}, {-100, 40}}, color = {0, 0, 127}));
  connect(LA201.activePort, LA201_RB.y) annotation(
    Line(points = {{-66, 24}, {-70, 24}}, color = {255, 0, 255}));
  connect(LA220.activePort, LA220_RB.y) annotation(
    Line(points = {{-28, 34}, {-32, 34}}, color = {255, 0, 255}));
  connect(LA202.activePort, LA202_RB.y) annotation(
    Line(points = {{-28, 24}, {-32, 24}}, color = {255, 0, 255}));
  connect(LA230.activePort, LA230_RB.y) annotation(
    Line(points = {{12, 34}, {6, 34}}, color = {255, 0, 255}));
  connect(LA203.activePort, LA203_RB.y) annotation(
    Line(points = {{12, 24}, {6, 24}}, color = {255, 0, 255}));
  connect(LA230_RB.u, LI213.y) annotation(
    Line(points = {{0, 34}, {-24, 34}, {-24, 40}}, color = {0, 0, 127}));
  connect(LA203_RB.u, LI213.y) annotation(
    Line(points = {{0, 24}, {-24, 24}, {-24, 40}}, color = {0, 0, 127}));
  connect(LA220_RB.u, LI212.y) annotation(
    Line(points = {{-38, 34}, {-62, 34}, {-62, 40}}, color = {0, 0, 127}));
  connect(LA202_RB.u, LI212.y) annotation(
    Line(points = {{-38, 24}, {-62, 24}, {-62, 40}}, color = {0, 0, 127}));
  connect(TI262.port, Pipe_B204_V207.port_a) annotation(
    Line(points = {{70, 14}, {62, 14}, {62, 8}, {48, 8}}, color = {0, 127, 255}));
  connect(pipe_P201_FI271.port_b, FI271.port_a) annotation(
    Line(points = {{14, -40}, {14, -34}}, color = {0, 127, 255}));
  connect(pipe_P201_FI271.port_a, P201.port_b) annotation(
    Line(points = {{14, -50}, {14, -54}, {-2, -54}}, color = {0, 127, 255}));
  connect(ActuatorControl.y[1], V201.opening) annotation(
    Line(points = {{-168, -6}, {-92, -6}, {-92, -12}}, color = {0, 0, 127}));
  connect(ActuatorControl.y[2], V202.opening) annotation(
    Line(points = {{-168, -6}, {-54, -6}, {-54, -10}}, color = {0, 0, 127}));
  connect(ActuatorControl.y[3], V203.opening) annotation(
    Line(points = {{-168, -6}, {-18, -6}, {-18, -8}}, color = {0, 0, 127}));
  connect(ActuatorControl.y[4], V206.opening) annotation(
    Line(points = {{-168, -6}, {-122, -6}, {-122, 60}, {-18, 60}, {-18, 66}}, color = {0, 0, 127}));
  connect(ActuatorControl.y[5], V205.opening) annotation(
    Line(points = {{-168, -6}, {-122, -6}, {-122, 60}, {-54, 60}, {-54, 68}}, color = {0, 0, 127}));
  connect(ActuatorControl.y[6], V204.opening) annotation(
    Line(points = {{-168, -6}, {-122, -6}, {-122, 60}, {-92, 60}, {-92, 70}}, color = {0, 0, 127}));
  connect(ActuatorControl.y[7], V209.opening) annotation(
    Line(points = {{-168, -6}, {-122, -6}, {-122, -90}, {154, -90}, {154, 2}, {120, 2}, {120, -6}}, color = {0, 0, 127}));
  connect(ActuatorControl.y[8], P201_Characteristic.u) annotation(
    Line(points = {{-168, -6}, {-122, -6}, {-122, -70}, {-102, -70}}, color = {0, 0, 127}));
  connect(ActuatorControl.y[9], P202_Characteristic.u) annotation(
    Line(points = {{-168, -6}, {-122, -6}, {-122, -90}, {34, -90}, {34, -70}}, color = {0, 0, 127}));
  annotation(
    uses(Modelica(version = "4.0.0")),
 //good results with IDA, max 1 Integration and 1 Processor. Still need to figure out optimal solver setup
 // cvode produces veery fast results
    Diagram(coordinateSystem(extent = {{-320, 120}, {160, -180}})),
    version = "",
    experiment(StartTime = 0, StopTime = 600, Tolerance = 1e-05, Interval = 1),
    __OpenModelica_commandLineOptions = "--matchingAlgorithm=PFPlusExt --indexReductionMethod=dynamicStateSelection -d=initialization,NLSanalyticJacobian",
    __OpenModelica_simulationFlags(lv = "LOG_STDOUT,LOG_ASSERT,LOG_STATS", s = "cvode"));
  connect(FI271.port_b, pipe_FI271_Tee4.port_a);
  connect(pipe_FI271_Tee4.port_b, Tee4.port_1);
  connect(Tee4.port_2, pipe_Tee4_B204.port_a);
  connect(pipe_Tee4_B204.port_b, tank_B204.topPorts[1]);
  connect(Tee4.port_3, pipe_Tee4_V211.port_a);
  connect(pipe_Tee4_V211.port_b, V211.port_a);
  connect(V211.port_b, Junction_V211.port_1);
  connect(Junction_V211.port_2, V211_to_X203.port_a);
  connect(V211_to_X203.port_b, X203.ports[1]);
  connect(Junction_V211.port_3, V211_to_B201.port_a);
  connect(V211_to_B201.port_b, pipe_V211_B201.port_a);
  connect(pipe_V211_B201.port_b, tank_B201.topPorts[2]);
  connect(V203.port_b, pipe_V203_Tee3.port_a);
  connect(pipe_V203_Tee3.port_b, Tee3.port_1);
  connect(Tee3.port_2, pipe_Tee3_Tee2.port_a);
  connect(pipe_Tee3_Tee2.port_b, Tee2.port_3);
  connect(Tee3.port_3, pipe_Tee3_V210.port_a);
  connect(pipe_Tee3_V210.port_b, V210.port_a);
  connect(V210.port_b, pipe_V210_Tee5.port_a);
  connect(pipe_V210_Tee5.port_b, Tee5.port_3);
  connect(Pipe_B204_V207.port_b, Tee5.port_1);
  connect(Tee5.port_2, pipe_Tee5_V212.port_a);
  connect(pipe_Tee5_V212.port_b, V212.port_a);
end ModVA_faultcapable;
