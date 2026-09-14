function app_new = Pichia_pastoris(app)

% Append the current index by 1
previdx = app.nxtidx; % previous index
idx = previdx + 1;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Feeding

% Declare feeding rate with zero and adjust the value afterwards
app.v.FR1(idx) = 0;
app.v.FR2(idx) = 0;

% Feeding is predefined as zero but if one of the following condition is
% true, feeding will take place. The hierachy is important to only allow
% one type of feeding
if app.switch_exp
    %% Exponential feed phase
    k = num2str(app.p.R_feed);
    % Calculate feeding rate FR(t)
    FRwj = app.p.(['FR' k 'j']);
    qxpxwj = app.p.(['qXpX' k 'w']);
    tj = app.p.(['t' k 'j']);
    FR = FRwj*exp(qxpxwj*(app.t(previdx)-tj));
    if FR < app.p.(['FR' k 'max'])
        app.v.(['FR' k])(previdx) = FR;
    else
        msg = sprintf("The desired pumping capacity for FR%i is greater than the maximum pumping capacity.",k);
        fprintf(append(msg,"\n"));
        logMessage(app.Startingscreen, msg)
        app.switch_exp = false;
    end

elseif app.switch_pulse
    %% Pulse feed phase

    k = num2str(app.p.R_feed);
    app.v.(['FR' k])(previdx) = app.p.(['FR' k 'max']) * app.p.(['kR' k]);

elseif app.p.Mode_pO2 == 4
    %% pO2 feed
    % Calculate deviation from setpoint
    cEfeedpO2             = app.p.pO2w-app.v.pO2(previdx); % Error/Controller difference between measured pO2 and Setpoint e = (w-x)
    app.a.cE_feedpO2        = (cEfeedpO2+0.001/app.a.deltat*app.a.cE_feedpO2)/(0.001/app.a.deltat+1); % Filtered error through a PT1 delay with T = 0.001 and deltat
    app.a.ce_feedpO2(idx) = app.a.cE_feedpO2/(100-0); % Normalized controller difference e = (w-x)/(w_max - w_min); [-1,+1]

    % Calculate controller outputs
    app.a.cP_feedpO2 = app.a.ce_feedpO2(previdx)*app.p.KP_feedpO2; % P-part of controller with KP = -2.0
    app.a.cI_feedpO2 = app.a.cI_feedpO2+(app.a.ce_feedpO2(previdx)+app.a.ce_feedpO2(end-1))/2*app.a.deltat*app.p.KI_feedpO2; % I-part of controller with KI = -15.0 and deltat
    app.a.cD_feedpO2 = (app.a.ce_feedpO2(previdx)-app.a.ce_feedpO2(end-1))/app.a.deltat*app.p.KD_feedpO2; % D-part of controller with KD = -0.009

    % Calculation of new relative setpoint for feed pump
    % PID sum in percent
    app.a.yfeedpO2  = ((app.a.cP_feedpO2+app.a.cI_feedpO2+app.a.cD_feedpO2)*100+app.a.yfeedpO2)/2;

    % Define limits for new setpoint
    if app.a.yfeedpO2 < 0
        app.a.yfeedpO2 = 0;
    elseif app.a.yfeedpO2 > 100
        app.a.yfeedpO2 = 100;
    end
    % Maybe add a parameter for reservoir selection later
    % Here reservoir 1 is standard
    % Calculation of new agitation speed setpoint [l/h]
    app.v.FR1(idx) = app.a.yfeedpO2/100*app.p.FR1max;

elseif app.p.f_feed == 1 % feed control as second priority
    % Current reservoir
    n = num2str(app.p.R_feed);
    %% Constant feeding
    if app.p.Mode_feed == 0
        % Set pump rate in relation to FRmax
        app.v.(['FR' n])(previdx) = app.p.(['FR' n 'w']);
    elseif app.p.Mode_feed == 1
        %% Closed-loop feed control
        cSLw = app.p.(['cS' n 'Lw']); % substrate concentration set point
        cSL = app.v.(['cS' n 'Lm'])(previdx); % Here the measured value as a controlled value
        cSLwmax = app.p.(['cS' n 'R' n]) * 0.2; % Maximum allowed set point
        cSLwmin = 0.01;                         % Minimum allowed set point
        % Calculate deviation from setpoint
        cEfeedR           = cSLw - cSL; % Error/Controller difference between measured pO2 and Setpoint e = (w-x)
        T                 = 0.001; % Time delay in h
        app.a.(['cE_feedR' n]) = (cEfeedR+T/app.a.deltat*app.a.(['cE_feedR' n]))/(T/app.a.deltat+1); % Error filtered through a time delay of first order with delta t and T = 0.001
        app.a.(['ce_feedR' n])(idx) = app.a.(['cE_feedR' n])/(cSLwmax-cSLwmin); % Normalized controller difference e = (w-x)/(w_max-w_min); [-1,+1], 75% of substrate concentration in reservoir as max, 0.01 g/l min

        % Calculate controller gains
        app.a.(['cP_feedR' n])        = app.a.(['ce_feedR' n])(previdx)*app.p.(['KP_feedR' n]); % P-part of controller with KP = 10.0
        app.a.(['cI_feedR' n])        = app.a.(['cI_feedR' n]) + (app.a.(['ce_feedR' n])(previdx) + app.a.(['ce_feedR' n])(end-1)) / 2 * app.a.deltat * app.p.(['KI_feedR' n]); % I-part of controller with KI = 1000 and with time increment deltat
        app.a.(['cD_feedR' n])        = (app.a.(['ce_feedR' n])(previdx)-app.a.(['ce_feedR' n])(end-1))/app.a.deltat*app.p.(['KD_feedR' n]); % D-part of controller with KD = 0.015

        % Calculation of new relative setpoint for rump rate
        yFR = app.a.(['cP_feedR' n])+app.a.(['cI_feedR' n])+app.a.(['cD_feedR' n]); % PID sum

        % Define limits for new setpoint
        if yFR < 0
            yFR = 0;
        elseif yFR > 1
            yFR = 1;
        end
        % Set pump rate in relation to FRmax
        app.v.(['FR' n])(previdx) = app.p.(['FR' n 'max']) * yFR;
    end
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% pO2 control
% Check if aeration with pure nitrogen or pure carbon dioxide
% is turned on
if app.p.f_aeration == 1
    if app.p.f_N2 == 1
        app.v.FnN2(idx) = app.p.FnN2w;
    else
        app.v.FnN2(idx) = 0;
    end

    if app.p.f_CO2 == 1
        app.v.FnCO2(idx) = app.p.FnCO2w;
    else
        app.v.FnCO2(idx) = 0;
    end
end
% Calculation of quasi stationary SPC-actual values
switch app.p.Mode_pO2
    case 1 % pO2 agitation
        % Calculate deviation from setpoint
        cEagi             = app.p.pO2w-app.v.pO2(previdx); % Error/Controller difference between measured pO2 and Setpoint e = (w-x)
        T                 = 0.001; % Time delay in h
        app.a.cE_agi        = (cEagi+T/app.a.deltat*app.a.cE_agi)/(T/app.a.deltat+1); % Error filtered through a time delay of first order with delta t and T = 0.001
        app.a.ce_agi(idx) = app.a.cE_agi/(100-1); % Normalized controller difference e = (w-x)/(w_max-w_min); [-1,+1]

        % Calculate controller gains
        app.a.cP_agi        = app.a.ce_agi(previdx)*app.p.KP_agi; % P-part of controller with KP = 10.0
        app.a.cI_agi        = app.a.cI_agi + (app.a.ce_agi(previdx) + app.a.ce_agi(end-1)) / 2 * app.a.deltat * app.p.KI_agi; % I-part of controller with KI = 1000 and with time increment deltat
        app.a.cD_agi        = (app.a.ce_agi(previdx)-app.a.ce_agi(end-1))/app.a.deltat*app.p.KD_agi; % D-part of controller with KD = 0.015 and with time increment deltat PARAMETER ANGEPASST VON 0.25, DA SONST SCHWINGUNG ZU GROß

        % Calculation of new relative setpoint for agitation
        % speed
        yNSt = app.a.cP_agi+app.a.cI_agi+app.a.cD_agi; % PID sum

        % Define limits for new setpoint
        if yNSt < 0.3
            yNSt = 0.3;
        elseif yNSt > 1
            yNSt = 1;
        end

        % Calculation of new agitation speed setpoint [1/min]
        app.v.NSt(idx) = yNSt*app.p.NStmax;

    case 2 % pO2 aeration

        % Calculate deviation from setpoint
        cEaeration             = app.p.pO2w-app.v.pO2(previdx); % Error/Controller difference between measured pO2 and Setpoint e = (w-x)
        app.a.cE_aeration        = (cEaeration+0.001/app.a.deltat*app.a.cE_aeration)/(0.001/app.a.deltat+1); % Filtered error through a PT1 delay with T = 0.001 and deltat
        app.a.ce_aeration(idx) = app.a.cE_aeration(previdx)/(100-1); % Normalized controller difference e = (w-x)/(w_max - w_min); [-1,+1]

        % Calculate controller gains
        app.a.cP_aeration = app.a.ce_aeration(previdx)*app.p.KP_aeration; % P-part of controller with KP = 20.0
        app.a.cI_aeration = app.a.cI_aeration+(app.a.ce_aeration(previdx)+app.a.ce_aeration(end-1))/2*app.a.deltat*app.p.KI_aeration; % I-part of controller with KI = 0.003 with time increment 0.005 h
        app.a.cD_aeration = (app.a.ce_aeration(previdx)-app.a.ce_aeration(end-1))/app.a.deltat*app.p.KD_aeration; % D-part of controller with KD = 0.0188

        % Calculation of new setpoint for aeration rate (add O2
        % aeration if AIR aeration is no longer sufficient)
        yaeration  = (app.a.cP_aeration+app.a.cI_aeration+app.a.cD_aeration)*100; % PID sum in percent
        diff       = 0;

        % Define limits for new setpoint
        if yaeration < 30
            yaeration = 30;
        elseif yaeration > 100
            diff      = yaeration-100;
            if diff > 100
                diff = 100;
            end
            yaeration = 100;
        end

        % Calculation of setpoints for AIR and O2 aeration [l/h]
        app.v.FnAIR(idx) = yaeration/100*app.p.FnAIRmax;
        app.v.FnO2(idx) = diff/100*app.p.FnO2max;

        % Calculate overall aeration rate [l/h]
        app.v.FnG(idx) = app.v.FnAIR(previdx)+app.v.FnO2(previdx)+app.v.FnN2(previdx)+app.v.FnCO2(previdx);

    case 3 % pO2 gasmix

        % Calculate deviation from setpoint
        cEgasmix             = app.p.pO2w-app.v.pO2(previdx); % Error/Controller difference between measured pO2 and Setpoint e = (w-x)
        app.a.cE_gasmix        = (cEgasmix+0.001/app.a.deltat*app.a.cE_gasmix)/(0.001/app.a.deltat+1); % Filtered error through a PT1 delay with T = 0.001 and deltat
        app.a.ce_gasmix(idx) = app.a.cE_gasmix(previdx)/(1-app.p.xOAIR); % Normalized controller difference e = (w-x)/(w_max - w_min); [-1,+1]

        app.a.cP_gasmix        = app.a.ce_gasmix(previdx)*app.p.KP_gasmix; % P-part of controller with KP = 0.4
        app.a.cI_gasmix(idx) = app.a.cI_gasmix(previdx)+(app.a.ce_gasmix(previdx)+app.a.ce_gasmix(end-1))/2*app.a.deltat*app.p.KI_gasmix; % I-part of controller with KI = 0.003 with time increment 0.005 h
        app.a.cD_gasmix        = (app.a.ce_gasmix(previdx)-app.a.ce_gasmix(end-1))/app.a.deltat*app.p.KD_gasmix; % D-part of controller with KD = 0.0005

        % Calculation of new relative setpoint for xOGin
        ygasmix  = (app.a.cP_gasmix+app.a.cI_gasmix(previdx)+app.a.cD_gasmix(previdx))*100; % PID sum in percent

        % Define limits for new setpoint
        if ygasmix < app.p.xOAIR*100
            ygasmix = app.p.xOAIR*100;
        elseif ygasmix > 100
            ygasmix = 100;
        end

        % Calculation of setpoint fir xOGin [-]
        xOGinw = ygasmix/100*1;

        % Calculation of AIR and O2 aeration rates [l/min]
        app.v.FnAIR(idx)    = (app.p.FnGw*(xOGinw-1))/(app.p.xOAIR-1);
        app.v.FnO2(idx)     = app.p.FnGw-app.v.FnAIR(previdx); % HIER NOCHMAL CHECKEN

        % Calculation of overall aeration rate [l/min]
        app.v.FnG(idx) = app.v.FnAIR(previdx)+app.v.FnO2(previdx)+app.v.FnN2(previdx)+app.v.FnCO2(previdx);

end
% pO2 feed control is handled in the feeding section and therefore cannot run in parallel with the exp feed or pulse feed

% Set stirrer speed if it is not pO2-controlled [1/min]
if app.p.Mode_pO2 ~= 1
    if app.p.f_motor == 1
        app.v.NSt(idx) = app.p.NStw;
    else
        app.v.NSt(idx) = 0;
    end
end

%% Aeration rate

% Calculate aeration rate [l/min]
if app.p.Mode_pO2 ~= 2 && app.p.Mode_pO2 ~= 3
    if app.p.f_aeration == 1
        if app.p.f_air == 1
            app.v.FnAIR(idx) = app.p.FnAIRw;
        else
            app.v.FnAIR(idx) = 0;
        end

        if app.p.f_O2 == 1
            app.v.FnO2(idx) = app.p.FnO2w;
        else
            app.v.FnAIR(idx) = 0;
        end

        % Total unfiltered aeration rate
        app.v.FnG(idx) = app.v.FnAIR(previdx)+app.v.FnO2(previdx)+app.v.FnN2(previdx)+app.v.FnCO2(previdx);
    else
        app.v.FnG(idx)  = 0;
    end
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Liquid Weight Control
if app.p.Mode_harvest  == 1

    % Calculate difference to setpoint
    cELW             = app.v.VL(previdx)*app.p.rhoL-app.p.LWw; % Error/Controller difference between measured liquid weight and Setpoint e = (w-x)
    app.a.cE_LW        = (cELW+0.001/app.a.deltat*app.a.cE_LW)/(0.001/app.a.deltat+1); % Error filtered through a time delay of first order with deltat and T = 0.001 h
    app.a.ce_LW(idx) = app.a.cE_LW/(app.p.VLmax*app.p.rhoL-app.p.VLmin*app.p.rhoL); % Normalized controller difference e = (w-x)/(w_max - w_min); [-1,+1]

    % Calculate controller gains
    cP_LW            = app.a.ce_LW(previdx)*app.p.KP_LW; % P-part of controller with KP = 10.0
    app.a.cI_LW(idx) = app.a.cI_LW(previdx)+(app.a.ce_LW(previdx)+app.a.ce_LW(end-1))/2*app.a.deltat*app.p.KI_LW; % I-part of controller with KI = 0.3 and with time increment deltat
    cD_LW            = (app.a.ce_LW(previdx)-app.a.ce_LW(end-1))/app.a.deltat*app.p.KD_LW; % D-part of controller with KD = 1.0

    % Calculation of new relative setpoint for harvest pump
    yLW  = (cP_LW+app.a.cI_LW(previdx)+cD_LW)*100; % PID sum in percent

    % Define limits for new setpoint
    if yLW < 0
        yLW = 0;
    elseif yLW > 100
        yLW = 100;
    end

    % Calculation of new setpoint for harvest pump [l/h]
    app.v.FH(idx) = yLW/100*app.p.FHmax;
else
    % Set harvest rate with harvest pump ON/OFF [l/h]
    if app.p.f_harvest == 1
        app.v.FH(idx) = app.p.FHrelw/100*app.p.FHmax;
    else
        app.v.FH(idx) = 0;
    end
end

% Calculate molefraction at reactor inlet [-]
if app.v.FnG(previdx) > 0
    app.v.xOGin(idx) = (app.p.xOAIR*app.v.FnAIR(previdx)+app.v.FnO2(previdx))/app.v.FnG(previdx);
    %app.v.xCGin(idx) = (app.p.xCAIR*app.v.FnAIR(previdx))/app.v.FnG(previdx); % CO2 term was deleted as no aeration with CO2 will take place in this simulation
else
    app.v.xOGin(idx) = 0;
    %app.v.xCGin(idx) = 0;
end

% Set tONi to time of inoculation, if it has already taken
% place [h]
if app.a.ToI ~= 0
    tONi = app.a.ToI;
end

% Calculate anti foam addition activity
if app.p.f_antifoam == 1 && app.a.ToI ~= 0
    TON   = app.t(previdx)-tONi;
    AAFin = app.p.AAFtast*app.p.VAF^(TON/app.p.Ttast);
else
    tONi  = app.t(previdx);
    AAFin = 0;
    TON   = 0;
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% pH Control (Manual)
if app.p.Mode_pH == 0
    % Calculation of titration rate with alkali pump ON/OFF [l/h]
    if app.p.f_alkali == 1
        app.v.FT2(idx) = app.p.FT2max;
    else
        app.v.FT2(idx) = 0;
    end

    % Calculation of titration rate with acid pump ON/OFF [l/h]
    if app.p.f_acid == 1
        app.v.FT1(idx) = app.p.FT1max;
    else
        app.v.FT1(idx) = 0;
    end
end

%% pH Control (Auto)
if app.p.Mode_pH == 1
    % Calculation of pH difference to Setpoint and
    % corresponding controller output as setpoint for
    % acid/alkali pumps (Cascade Control)
    if abs(app.p.pHw-app.v.pHL(previdx)) < 0.1
        app.v.FT1(idx) = 0;
        app.v.FT2(idx) = 0;
    else
        % Calculate difference to setpoint
        epH       = app.p.pHw-app.v.pHL(previdx); % Error/Controller difference between pH in Liquid and Setpoint e = (w-x)
        app.a.cEpH  = (epH+0.001/app.a.deltat*app.a.cEpH)/(0.001/app.a.deltat+1); % Filtered error through a PT1 delay with T = 0.001 h and deltat
        cepH      = app.a.cEpH/(app.p.pHLmaxgr-app.p.pHLmingr); % Normalized controller difference e = (w-x) / (w_max - w_min) ; [-1,+1]

        % Calculate controller gains
        cP_pH  = cepH*app.p.KP_pH; % P-part of controller with KP = 10000

        % Calculation of new relative difference setpoint
        % by master controller
        % in percent
        ypH    = cP_pH*100;
        if ypH > 100
            ypH = 100;
        elseif ypH < -100
            ypH = -100;
        end

        % Calculation of deviation from difference setpoint
        cEypH  = app.p.ypH_SET-(ypH/100); % Error/Controller difference between measured pH difference to setpoint and wanted difference
        ceypH  = cEypH/(1-(-1)); % Normalized controller difference if the maximum ypH is 1 and the minimum ypH is -1

        % Calculation of new setpoint for acid/alkali pump
        % by slave controller
        % [l/h]
        cP_ypH = ceypH*100; % P-part of controller in percent

        % Calculation of T1 or T2 flow rate
        % Define limits for new setpoint
        if cP_ypH > 0
            yT1 = cP_ypH*app.p.KP_pH2a;
            if yT1 > 100
                yT1 = 100;
            end
            app.v.FT1(idx) = yT1/100*app.p.FT2max;
            app.v.FT2(idx) = 0;
        elseif cP_ypH < 0
            yT2 = cP_ypH*app.p.KP_pH2b;
            if yT2 > 100
                yT2 = 100;
            end
            app.v.FT1(idx) = 0;
            app.v.FT2(idx) = yT2/100*app.p.FT1max;
        else
            app.v.FT1(idx) = 0;
            app.v.FT2(idx) = 0;
        end
    end
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Temperature Control (Manual)
if app.p.Mode_temp == 0
    % Calculation of cooling power with cooling flux ON/OFF
    % [kg/h]
    if app.p.f_cooling == 1
        app.p.mdotC = app.p.mdotCmax;
    else
        app.p.mdotC = 0;
    end

    % Calculation of heating power with heating rod ON/OFF [W]
    if app.p.f_heating == 1
        PH = app.p.PHmax;
    else
        PH = 0;
    end

    %% Temperature Control (Auto)
elseif app.p.Mode_temp == 1
    % Calculation of temperature difference to Setpoint and corresponding controller parameters for temperature control at split range
    % A PT1 controller is used to filter the error signal and dampen its fluctuations
    e              = app.p.thetaLw-app.v.thetaL(previdx); % Error/Controller difference between Temperature in Liquid and Setpoint e = (w-x)
    app.a.cE         = (e+0.001/app.a.deltat*app.a.cE)/(0.001/app.a.deltat+1); % Filtered error through a PT1 delay with T = 0.001 h and deltat
    app.a.ce(idx)  = app.a.cE/(app.p.thetaLmaxgr-app.p.thetaLmingr); % Normalized controller difference e = (w-x) / (w_max - w_min) ; [-1,+1]

    app.a.cP_Part        = app.a.ce(previdx)*app.p.KP_temp1; % P-part of controller with KP = 0.1
    app.a.cI_Part(idx) = app.a.cI_Part(previdx)+(app.a.ce(previdx)+app.a.ce(end-1))/2*app.a.deltat*app.p.KI_temp1; % I-part of controller with KI = 0.01 with time increment deltat

    % Calculation of steam mass flux and cooling flux in case of steam heating at split-range
    wDJ  = app.a.cP_Part+app.a.cI_Part(previdx)+app.p.thetaDJ_WP; % PI sum + Workingpoint (ThetaDJw = ThetaLw)

    cDJ  = wDJ-app.a.thetaDJ; % Error/controller difference between temperature in double jacket and the calculated setpoint cDJ
    CDJ  = cDJ/(100-0); % Normalized controller difference assuming the double jacket should not be cooler than 0°C or hotter than 100°C

    yDJ = CDJ*100; % Master controller output in percent

    % Define limits for new setpoint
    if yDJ > 100
        yDJ = 100;
    elseif yDJ < -100
        yDJ = -100;
    end

    if yDJ > 0
        yH    = yDJ*app.p.KP_temp2h; % Slave controller output with KP = 10
        if yH > 100
            yH = 100;
        end
        app.p.mdotH = (yH/100)*app.p.mdotHmax;
        app.p.mdotC = 0;
    else
        yC    = -yDJ*app.p.KP_temp2c; % Slave controller output with KP = -10
        if yC < -100
            yC = -100;
        end
        app.p.mdotH = 0;
        app.p.mdotC = (yC/100)*app.p.mdotCmax*10;
    end
end

% Eigenvalues of foam and anti foam deq. [1/h]
lambdaF  = -app.v.AAF(previdx)/app.p.tauF0/(1+app.p.KFpX*app.v.cXL(previdx));
lambdaAF = -app.v.cXL(previdx)/app.p.KAF;
%% Volume
DR1 = 0;
DR2 = 0;
DT1 = 0;
DT2 = 0;
if app.v.VL(previdx) > 0
    if app.v.FR1(previdx) > 0
        DR1 = app.v.FR1(previdx)/app.v.VL(previdx); % Dilution rate [1/h]
    end
    if app.v.FR2(previdx) > 0
        DR2 = app.v.FR2(previdx)/app.v.VL(previdx); % Dilution rate [1/h]
    end
    DT1 = app.v.FT1(previdx)/app.v.VL(previdx); % Refered acid titration rate [1/h]
    DT2 = app.v.FT2(previdx)/app.v.VL(previdx); % Refered alkali titration rate [1/h]
end
% Define ODE function for volume calculation
ODE_Vol       = @(t,yV) Pichia_ODE_Volume(app.v.FR1(previdx),app.v.FR2(previdx),app.v.FH(previdx),app.v.FT1(previdx),app.v.FT2(previdx),t,yV);

% Liquid volume balance
[~,yV] = ode15s(ODE_Vol,[0 app.a.deltat],[app.v.VL(previdx) app.v.VR1(previdx) app.v.VR2(previdx) app.v.VT2(previdx) app.v.VT1(previdx)]);
app.v.VL(idx)  = yV(end,1);
app.v.VR1(idx)  = yV(end,2);
app.v.VR2(idx)  = yV(end,3);
app.v.VT2(idx) = yV(end,4);
app.v.VT1(idx) = yV(end,5);

app.v.VR1in(idx) = app.p.VR10-app.v.VR1(previdx); % Volume added from glycerol reservoir
app.v.VR2in(idx) = app.p.VR20-app.v.VR2(previdx); % Volume added from methanol reservoir
app.v.Vbase(idx) = app.p.VT20-app.v.VT2(previdx);
app.v.Vacid(idx) = app.p.VT10-app.v.VT1(previdx);

% Refered dilution rate [1/h]
Din = DR1+DR2+DT1+DT2;
% Temperature liquid phase [K]
TL  = app.v.thetaL(previdx)+app.p.TnG;

% Pressure in reactor measured in gas phase [N/m^2]
if app.v.thetaL(previdx) < 100
    app.v.pG(idx) = app.a.pGw;
    %ExppDL        = 0;
    %pDL           = 0;
else
    ExppDL        = 10.9-2461/TL-2.065*log10(app.v.thetaL(previdx)/app.p.TnG);
    % Steam pressure in liquid phase
    pDL           = 9.8067*10^ExppDL;
    app.v.pG(idx) = pDL;
end

% Over pressure indication [bar]
app.a.deltapG = (app.v.pG(previdx)-app.p.pnG)/10^5;


% Quasistationary molar respiration quotient (offgas)
RQ_Z = app.v.xCO2(previdx)/100*(1-app.v.xOGin(previdx))-app.a.xCGin*(1-app.v.xO2(previdx)/100); % Check if xCGin is correct
RQ_N = app.v.xOGin(previdx)*(1-app.v.xCO2(previdx)/100)-app.v.xO2(previdx)/100*(1-app.a.xCGin);
if RQ_N ~= 0
    app.v.RQ(idx) = RQ_Z/RQ_N;
else
    app.v.RQ(idx) = 1;
end
if app.v.RQ(previdx) <= 0
    app.v.RQ(previdx) = 0.0001; % Avoid NaN error for C balance as it requires division by RQ
end

% to compare - RQ over metabolism
% RQ_int = app.a.yCpO*app.a.MO2/app.a.MCO2;

% Iterative calculation of pH in liquid phase
% Cations of the bufffer
y1 = (app.v.CB1Ltot(previdx)+2*app.v.CB2Ltot(previdx))/app.p.CH0;

% Anions of the buffer = total phosphoric acid
y2 = (app.v.CB1Ltot(previdx)+app.v.CB2Ltot(previdx))/app.p.CH0;

% Dissolved-CO2
y3 = app.v.CCLtot(previdx)/app.p.CH0;

% Product acetate
y4 = app.v.cP1L(previdx)/app.p.CH0;

% Titrated base
y5 = app.v.CAlLtot(previdx)/app.p.CH0;

% Titrated acid
y6 = app.v.CAcLtot(previdx)/app.p.CH0;

% Iterative solution
xpH    = 10^(7-app.v.pH(previdx));
QuotpH = 0.9;

% Iteration
for i = 1:100
    if (QuotpH <= 0.999 || QuotpH >= 1.001) && xpH >= 0 % If xpH < 0 NaN error occurs SET FLAG THIS WOULD HAVE HAPPENED
        app.a.xpHkm1 = xpH;
        fpH0    = xpH^2-1;
        fpH1    = xpH*y1;
        fpH2    = -(app.a.ApH*xpH^2+2*app.a.BpH*xpH+3*app.a.CpH)*xpH/(xpH^3+app.a.ApH*xpH^2+app.a.BpH*xpH+app.a.CpH)*y2;
        fpH3    = -(app.a.DpH+2*app.a.EpH/xpH)*y3;
        fpH4    = -app.a.FpH*xpH/(app.a.FpH+xpH)*y4;
        fpH5    = app.a.GpH*xpH^2/(1+app.a.GpH*xpH)*y5;
        fpH6    = -(app.a.HpH*xpH+2*app.a.IpH)*xpH/(xpH^2+app.a.HpH*xpH+app.a.IpH)*y6;
        fpH     = fpH0+fpH1+fpH2+fpH3+fpH4+fpH5+fpH6;
        fstrpH0 = 2*xpH;
        fstrpH1 = y1;
        fstrpH2 = -((app.a.ApH^2-2*app.a.BpH)*xpH^4+ ...
            (2*app.a.ApH*app.a.BpH-6*app.a.CpH)*xpH^3+ ...
            2*app.a.BpH^2*xpH^2+4*app.a.BpH*app.a.CpH*xpH+ ...
            3*app.a.CpH^2)/((xpH^3+app.a.ApH*xpH^2+app.a.BpH*xpH+app.a.CpH)^2)*y2;
        fstrpH3 = 2*app.a.EpH/(xpH*xpH)*y3;
        fstrpH4 = -app.a.FpH^2/((xpH+app.a.FpH)^2)*y4;
        fstrpH5 = app.a.GpH*xpH*(2+app.a.GpH*xpH)/((1+app.a.GpH*xpH)^2)*y5;
        fstrpH6 = -((app.a.HpH^2-2*app.a.IpH)*xpH^2+2*app.a.HpH*app.a.IpH*xpH+2*app.a.IpH^2)/((xpH^2+app.a.HpH*xpH+app.a.IpH)^2)*y6;
        fstrpH  = fstrpH0+fstrpH1+fstrpH2+fstrpH3+fstrpH4+fstrpH5+fstrpH6;
        xpH     = xpH-fpH/fstrpH;
        QuotpH  = app.a.xpHkm1/xpH;
    else
        break
    end
end

if xpH < 0
    xpH = -xpH; % Set flag that this occured
end

% pH value in liquid phase
app.v.pHL(idx) = 7-log10(xpH);

% Molar concentration of the H+ ions in the liquid phase
CHL = xpH*app.p.CH0;
% Influence of temperature and pH of the growth
if app.v.pHL(previdx) >= app.p.pHLmingr && app.v.pHL(previdx) <= app.p.pHLmaxgr
    fpH    = (app.v.pHL(previdx)-app.p.pHLmingr)*(app.v.pHL(previdx)-app.p.pHLmaxgr)/((app.v.pHL(previdx)-app.p.pHLmingr)*(app.v.pHL(previdx)-app.p.pHLmaxgr)-(app.v.pHL(previdx)-app.p.pHLoptgr)^2);
else
    fpH    = 0;
end
if app.v.thetaL(previdx) >= app.p.thetaLmingr && app.v.thetaL(previdx) <= app.p.thetaLmaxgr
    ftheta = ((app.v.thetaL(previdx)-app.p.thetaLmaxgr)*(app.v.thetaL(previdx)-app.p.thetaLmingr)^2)/((app.p.thetaLoptgr-app.p.thetaLmingr)*((app.p.thetaLoptgr-app.p.thetaLmingr)*(app.v.thetaL(previdx)-app.p.thetaLoptgr)-(app.p.thetaLoptgr-app.p.thetaLmaxgr)*(app.p.thetaLoptgr+app.p.thetaLmingr-2*app.v.thetaL(previdx))));
else
    ftheta = 0;
end

% Maximum specific growth rate glycerol [1/h]
my1max = app.p.my1opt*fpH*ftheta;

% Maximum specific growth rate methanol [1/h]
%my2max = app.p.my2opt*fpH*ftheta; % Now calculated with qS2pXmax

% Maximum specific glycerol uptake rate [1/h]
app.a.qS1pXmax = (my1max+app.a.mySm)/app.p.yXpS1gr;

% Maximum specific methanol uptake rate [1/h]
% app.a.qS2pXmax = (my2max+app.a.mySm)/app.p.yXpS2gr; % Old model

% Alternative calculation of qS2pXmax (Cornelissen)
cS2Lopt = sqrt(app.p.kS2*app.p.kI22); % g/l
app.a.qS2pXmax = app.p.qS2pXsup*(cS2Lopt/(app.p.kS2+cS2Lopt))*(app.p.kI22/(app.p.kI22+cS2Lopt)); % 1/h

% Optimal cellspecific growth rate (methanol dependend) [1/h]
app.p.my2opt = app.p.yXpS2gr*app.a.qS2pXmax-app.a.mySm;

% Maximum specific growth rate methanol [1/h]
my2max = app.p.my2opt*fpH*ftheta; % New model

%% Respiration
% Maximum specific oxygen uptake rate [1/h]
app.a.qOpXmax  = (my1max+app.a.mySm)/app.p.yXpOgr+app.p.qOpXm;

% Calculation of O2 quantities
% Maintenance O2 uptake rate [1/h]
app.v.OURm(idx)    = app.p.qOpXm*app.v.cXL(previdx);

% Maximum O2 uptake rate [1/h]
app.v.OURmax(idx)  = app.a.qOpXmax*app.v.cXL(previdx);

% Calculation of O2 Henry constant [Nm/kg]
app.a.HO2 = app.p.HnO2/(1+app.p.K1HO2*app.v.thetaL(previdx)+app.p.K2HO2*app.v.thetaL(previdx)^2+app.p.K3HO2*app.v.thetaL(previdx)^3+app.p.K4HO2*app.v.thetaL(previdx)^4);

% O2-concentration in liquid phase at 100 % pO2-indication
app.a.cOL100 = app.p.pGcal*app.p.xOGcal/app.a.HO2;

% Maximum potential O2 concentration in liquid phase [g/l]
app.a.cOLmax = app.v.pG(previdx)/app.a.HO2;

% Maximum oxygen supply rate [g/(l*h)]
if app.v.VL(previdx) > 0
    app.v.QO2max(idx) = app.v.FnG(previdx)*60*app.p.MO2/(app.p.VnM*app.v.VL(previdx));
else
    app.v.QO2max(idx) = 0;
end

% Maximum CO2 supply rate [g/(l*h)]
app.v.QCO2max(idx) = app.v.QO2max(previdx)*app.p.MCO2/app.p.MO2;

% Calculation of viscosity [Ns/m^2]
eta = app.p.etaXL*(app.p.etaH2O/app.p.etaXL)^(app.v.cXL(previdx)/app.p.cXLeta);

% Volume refered O2-transition coefficient kLa [1/h]
VLwert         = (app.v.VL(previdx)/app.p.VLmin)^app.p.alpha;
NStwert        = (app.v.NSt(previdx)/app.p.NStmax)^(3*app.p.alpha);
FGwert         = (app.v.FnG(previdx)/app.p.FnGmax)^app.p.beta;
etawert        = (eta/app.p.etaH2O)^app.p.gamma;

app.v.kLa(idx) = app.p.kLamin+app.p.kLamax*FGwert*NStwert/VLwert*etawert*(1-app.v.AAF(previdx));

% Theoretical maximum O2 transfer rate [g/(l*h)]
app.v.OTRmax(idx)  = app.v.kLa(previdx)*app.a.cOLmax;

% Calculation of Stanton coefficient of oxygen
if app.v.QO2max(previdx) > 0
    StO = app.v.OTRmax(previdx)/app.v.QO2max(previdx);
else
    StO = 10^20;
end

% Optimum O2 limiting transport rate
% OTRopt = app.v.OTRmax(previdx)/(1+StO);

% O2-pulp quantity in reactor liquid phase
app.v.xOL(idx) = app.v.cOL(previdx)/app.a.cOLmax;

% OTR [g/(l*h)]
app.v.OTR(idx) = app.v.OTRmax(previdx)*(app.v.xOGin(previdx)-app.v.xOL(previdx))*2/((1+StO-(1-app.v.RQ(previdx))*StO*app.v.xOL(previdx))+sqrt((1+StO-(1-app.v.RQ(previdx))*StO*app.v.xOL(previdx))^2-4*(1-app.v.RQ(previdx))*StO*(app.v.xOGin(previdx)-app.v.xOL(previdx))));
if app.v.OTR(previdx) < 0
    app.v.OTR(previdx) = 0;
end

% Calculation of quasistationary O2 gas phase mole fraction [-]
if app.v.OTR(previdx) ~= 0
    app.v.xOG(idx) = (app.v.QO2max(previdx)*app.v.xOGin(previdx)-app.v.OTR(previdx))/(app.v.QO2max(previdx)-(1-app.v.RQ(previdx))*app.v.OTR(previdx));
else
    app.v.xOG(idx) = app.v.xOGin(previdx);
end

% Calculation of CO2 Herny constant [Nm/kg]
app.a.HCO2 = app.p.HnCO2/(1+app.p.K1HCO2*app.v.thetaL(previdx)+app.p.K2HCO2*app.v.thetaL(previdx)^2+app.p.K3HCO2*app.v.thetaL(previdx)^3+app.p.K4HCO2*app.v.thetaL(previdx)^4);

% Maximum CO2 concentration [g/l]
app.a.cCLmax = app.v.pG(previdx)/app.a.HCO2;

% Dissolved CO2-concentration in liquid phase [g/l]
app.a.cCL = (CHL^2*app.p.MCO2*app.v.CCLtot(previdx))/(CHL^2+app.p.KC1*CHL+app.p.KC1*app.p.KC2);

% CO2-pulp quantity in reactor liquid phase [-]
app.a.xCL = app.a.cCL/app.a.cCLmax;

% Theoretical maximum CO2 transfer rate [g/(l*h)]
app.a.CTRmax = app.p.deltaCpO*app.v.kLa(previdx)*app.a.cCLmax;

% Stanton coefficient of CO2
if app.v.QCO2max(previdx) > 0
    app.a.StC = app.a.CTRmax/app.v.QCO2max(previdx);
else
    app.a.StC = 10^20;
end

% CO2 transfer rate
app.v.CTR(idx) = app.a.CTRmax*(app.a.xCGin-app.a.xCL)*2/((1+app.a.StC-(1-1/app.v.RQ(previdx))*app.a.StC*app.a.xCL)+sqrt((1+app.a.StC-(1-1/app.v.RQ(previdx))*app.a.StC*app.a.xCL)^2-4*(1-1/app.v.RQ(previdx))*app.a.StC*(app.a.xCGin-app.a.xCL)));

% Calculation of the quasistationary CO2 gas phase mole fraction
app.v.xCG(idx) = (app.v.QCO2max(previdx)*app.a.xCGin-app.v.CTR(previdx))/(app.v.QCO2max(previdx)-(1-1/app.v.RQ(previdx))*app.v.CTR(previdx));

% Optimum specific substrate uptake rate (no O2 limitation) [1/h]
if app.v.cS1L(previdx) <= 0
    qS1pXopt = 0;
else
    qS1pXopt = app.a.qS1pXmax*app.v.cS1L(previdx)/(app.v.cS1L(previdx)+app.p.kS1);
end

% Optimum specific substrate uptake rate 2 [1/h]
if app.v.cS2L(previdx) <= 0
    qS2pXopt = 0;
else
    qS2pXopt = app.a.qS2pXmax*app.v.cS2L(previdx)/(app.v.cS2L(previdx)+app.p.kS2)*app.p.kI21/(app.v.cS1L(previdx)+app.p.kI21);
end

% Specific cell growth rate at substrate limitation
qXpXSgr = app.p.yXpS1gr*qS1pXopt+app.p.yXpS2gr*qS2pXopt;

% Specific cell growth rate at O2 limitation
if app.v.cOL(previdx) <= 0
    qXpXOgr = 0;
else
    qXpXOgr = app.p.yXpOgr*(app.a.qOpXmax-app.p.qOpXm)*app.v.cOL(previdx)/(app.p.kO+app.v.cOL(previdx));
end

% Specific cell growth rate
if qXpXSgr < qXpXOgr
    qXpXgr = qXpXSgr;
    if any(app.p.f_Inoc == 1)
        %  "Substrate Limitation"
    end
else
    qXpXgr = qXpXOgr;
    if any(app.p.f_Inoc == 1)
        % "Oxygen Limitation"
    end
end

% Determine methanol toxicity and its influence on cell growth
% Toxicity turn on function
VS2tox = ((app.v.cS2L(previdx)./app.p.kS2tox).^app.p.kappatox)./(1+((app.v.cS2L(previdx)./app.p.kS2tox).^app.p.kappatox));

% Calculation of cell specific reaction rates
% Specific cell reaction rate
if any(app.p.f_Inoc == 1)
    app.v.qXpX(idx) = qXpXgr-app.a.mySm-VS2tox*app.p.qXpXtox;
else
    app.v.qXpX(idx) = 0;
end

% Specific substrate uptake rate glycerine [1/h]
SSG = qXpXgr/app.p.yXpS1gr;
if SSG < qS1pXopt
    qS1pX = SSG;
else
    qS1pX = qS1pXopt;
end

%% AOX induction for methanol metabolism
bS2script = app.p.aS2script + my2max;
bS2trans = app.p.aS2trans + my2max;
bS2act = app.p.aS2act + my2max;

% Turn on/turn Off functions
VS2ind = ((app.v.cS2L(previdx)/app.p.kS2ind)^app.p.kappaind)/(1+(app.v.cS2L(previdx)/app.p.kS2ind)^app.p.kappaind);
VS1rep = 1/(1+(app.v.cS1L(previdx)/app.p.kS1rep)^app.p.kapparep);

app.v.qS2pXind(idx) = VS1rep*VS2ind*app.p.qS2pXsup;

ODE_Induction = @(t,y) Pichia_Induction_Cornelissen(app.v.qXpX(previdx),app.v.qS2pXind(previdx),app.p.aS2script,app.p.aS2trans,app.p.aS2act,bS2script,bS2trans,bS2act,t,y);
[~,y] = ode15s(ODE_Induction,[0 app.a.deltat],[app.v.qS2pXscript(previdx), app.v.qS2pXtrans(previdx), app.v.qS2pXact(previdx)]);

app.v.qS2pXscript(idx) = y(end,1);
app.v.qS2pXtrans(idx) = y(end,2);
app.v.qS2pXact(idx) = y(end,3);

% Glycerol dependend methanol uptake rate [1/h]
app.v.qS2pX = app.v.qS2pXact(previdx)*(app.v.cS2L(previdx)/(app.p.kS2+app.v.cS2L(previdx)))*(app.p.kI22/(app.p.kI22+app.v.cS2L(previdx)))*(app.p.kI21/(app.p.kI21+app.v.cS1L(previdx)));

%% Target protein expression
bP1script = app.p.aP1script + my2max;
bP1trans = app.p.aP1trans + my2max;
bP1act = app.p.kP1alpha + my2max;

% Turn on/turn Off functions
VS2ind = ((app.v.cS2L(previdx)/app.p.kS2ind)^app.p.kappaind)/(1+(app.v.cS2L(previdx)/app.p.kS2ind)^app.p.kappaind);
VS1rep = 1/(1+(app.v.cS1L(previdx)/app.p.kS1rep)^app.p.kapparep);

app.v.qP1pXind(idx) = VS1rep*VS2ind*app.p.qP1pXsup;

delta_qP1pXscript = app.v.qP1pXscriptw - app.v.qP1pXscript; % Calculate control deviation
if length(app.t) > 1 && length(delta_qP1pXscript) > 1 % need at least two values for trapz()
    app.v.qP1pXscriptw(idx) = VS1rep*VS2ind*app.p.qP1pXmax; % Calculate scriptw for next cycle
    app.v.qP1pXback(idx) = app.p.KCP1script*(delta_qP1pXscript(previdx)+trapz(app.t,delta_qP1pXscript)/app.p.TIP1script);
else
    app.v.qP1pXscriptw(idx) = 0;
    app.v.qP1pXback(idx) = 0;
end
ODE_Expression = @(t,y) Pichia_Expression_Cornelissen(app.v.qXpX(previdx),app.v.qP1pXind(previdx),app.v.qP1pXback(previdx),app.p.aP1script,app.p.aP1trans,app.p.kP1alpha,bP1script,bP1trans,bP1act,t,y);

% IVP
[~,y] = ode15s(ODE_Expression, [0 app.a.deltat], [app.v.qP1pXscript(previdx),app.v.qP1pXtrans(previdx),app.v.qP1pXact(previdx)]);

app.v.qP1pXscript(idx) = y(end, 1);
app.v.qP1pXtrans(idx) = y(end, 2);
app.v.qP1pXact(idx) = y(end, 3);

% Glycerol and methanol dependend product formation rate [1/h]
app.v.qP1pX(idx) = app.v.qP1pXact(previdx);

% Specific ammonia uptake rate [1/h]
qAlpX = app.p.yAlpXgr*qXpXgr;

% Specific uptake rate of titrated acid [1/h]
qAcpX = app.p.yAcpXgr*qXpXgr;

% Specific oxygen uptake rate [1/h]
qOpX = qXpXgr/app.p.yXpOgr+app.p.qOpXm;

% Resulting O2 yield coeficient
%yXpO = app.p.yXpOgr*app.v.qXpX(previdx)/(app.v.qXpX(previdx)+app.a.myOm);

% Volumetric oxygen uptake rate [g/(l*h)] and kLa [1/h]
if any(app.p.f_Inoc == 1)
    app.v.OUR(idx) = qOpX*app.v.cXL(previdx);
else
    app.v.OUR(idx) = 0;
end

% Volumetric oCO2 production rate [g/(l*h)]
CER = app.p.yCpO*app.v.OUR(previdx);

% Specific production rate, S-limited, O2-inhibited [1/h]
% % qPpX = (app.p.yPpS1*qS1pXopt+app.p.yPpS2*qS2pXopt)*app.p.kIPO/(app.p.kIPO+app.v.cOL(previdx))-app.p.yPpS3*qS3pX;

% Calculation of ammonia transfer rate (volatile) [g/(l*h)]
AlTR = -app.p.KAlvol*app.v.FnG(previdx)*app.v.CAlLtot(previdx)*app.p.MAl/app.v.VL(previdx);

% Calculation of variables in the temperature systems
% Quasitationary calculation of the heat exchanger
% temperature
% Dilution rate of the steam flux [1/h]
if app.p.Mode_temp == 1
    DH = app.p.mdotH/app.a.mHmax;
end

% Time constant of the primary heating cycle [h]
tauHTh = app.a.mHmax*app.p.cH2O/(app.a.kHTh*app.p.AHTh);

% Dimensionless quantities
if app.p.Mode_temp == 1
    phiHTh = DH*tauHTh;
    phiHT  = app.p.mdotH/app.p.mdotT;
end

% Temperature of heating outlet
% Electrical heating [°C]
if app.p.Mode_temp == 0
    if app.p.f_heating == 1
        app.a.thetaTh = app.v.thetaD(previdx)+app.a.RT*PH;
    else
        app.a.thetaTh = app.v.thetaL(previdx); % Added this line to account for thetaTh when the heating power is turned off
    end
end

% Steam heating as alternative for electrical heating
if app.p.Mode_temp == 1
    app.a.thetaTh = ((1+phiHTh)*app.a.CHmax*app.v.thetaD(previdx)+phiHT*(app.a.CHmax*app.p.thetaHin+app.a.Qny))/(app.a.CHmax*(1+phiHTh+phiHT));
end

% Dilution rate of cooling flux [1/h]
DC     = app.p.mdotC/app.p.mC;
phiCTc = DC*app.a.tauCTc;

% Cooling outlet temperature [°C]
app.a.thetaTc = (phiCTc*app.p.thetaCin+(1+phiCTc)*app.a.phiTcC*app.a.thetaTh)/((1+app.a.phiTcC)*(1+phiCTc)-1);

% Cooling water outlet temperature [°C]
app.a.thetaC  = (phiCTc*app.p.thetaCin+app.a.thetaTc)/(1+phiCTc);

% Cascade control quantity
app.a.thetaDJ = app.a.thetaTc;

% Volumetric heat capacity of the liquid ohase and share of
% the wall [Wh/K]
CL = app.p.rhoL*app.v.VL(previdx)*app.p.cH2O+app.p.mWL*app.p.cW;

% Time constant liquid phase - double jacket [h]
tauLD = CL/(app.a.kDL*app.p.ADL);

% Time constant liquid phase - environment [h]
tauLU = CL/(app.a.kLU*app.p.ALU);

% Time constnat reactor liquid phase [h]
tauL = 1/(1/tauLD+1/tauLU);

% Microbiological heat generation [W]
QdotM = app.p.KHM*app.v.VL(previdx)*app.v.OUR(previdx);

% Thermal efficiency of the stirrer
QdotSt = app.p.KHSt*app.v.VL(previdx)*app.v.NSt(previdx)^3;

% DEFINITION OF DYNAMIC MODEL EQUATIONS
% Cell mass balances and inoculation
ODE_concbal = @(t,y) Pichia_ODE_Luttmann(app.v.qXpX(previdx),Din,app.p.cS1R1,qS1pX,app.p.cS2R1,app.v.qS2pX,app.p.cS1R2,app.p.cS2R2,app.p.cP1R1,app.p.cP1R2,app.v.qP1pX(previdx),app.p.kP1alpha,app.p.cOT1,app.p.cOT2,app.p.cOR1,app.p.cOR2,app.v.OTR(previdx),app.v.OUR(previdx),app.a.cOL100,app.p.TMpO2,DT1,app.p.CAcT1tot,qAcpX,app.p.MAc,DT2,app.p.CAlT2tot,qAlpX,AlTR,app.p.MAl,DR1,DR2,app.p.CCR1tot,app.p.CCT1tot,app.p.CCT2tot,app.v.CTR(previdx),CER,app.p.MCO2,app.v.pHL(previdx),app.p.TMpH,app.p.TMxO2,app.v.xOG(previdx),app.p.TMxCO2,app.v.xCG(previdx),lambdaF,app.p.qhpX,lambdaAF,AAFin,app.a.tauD,app.a.DD,app.a.thetaTc,app.a.tauDL,app.p.thetaU,app.a.tauDU,tauL,tauLD,tauLU,QdotM,QdotSt,CL,t,y);

% if all(app.a.inoculum == 0) || any(app.a.inoc_occ == 1)
[~,y] = ode15s(ODE_concbal,[0 app.a.deltat],[app.v.cXL(previdx) app.v.cS1L(previdx) app.v.cS2L(previdx) app.v.cP1X(previdx) app.v.cP1L(previdx) app.v.cOL(previdx) app.v.pO2(previdx) app.v.CB1Ltot(previdx) app.v.CB2Ltot(previdx) app.v.CAcLtot(previdx) app.v.CAlLtot(previdx) app.v.CCLtot(previdx) app.v.pH(previdx) app.v.xO2(previdx) app.v.xCO2(previdx) app.v.hF(previdx) app.v.AAF(previdx) app.v.thetaD(previdx) app.v.thetaL(previdx)]);
% all y values can not be smaller than 0
for i = 1:18
    if y(end,i) < 0
        y(end,i) = 0;
    end
end
% Check if inoculation occured
if app.p.f_Inoc == 1 && app.a.inoc_occ == 0
    app.v.cXL(idx) = app.p.cXL0; % [g/l]
    app.a.ToI        = app.t(previdx);
    app.a.inoc_occ   = 1;
    logMessage(app.Startingscreen, app.projectID, "Inoculation occured")
else
    app.v.cXL(idx)    = y(end,1);
end
app.v.cS1L(idx)   = y(end,2);
app.v.cS2L(idx)   = y(end,3);
app.v.cP1X(idx)   = y(end,4);
app.v.cP1L(idx)   = y(end,5);
app.v.cOL(idx)    = y(end,6);
app.v.pO2(idx)    = y(end,7);
app.v.CB1Ltot(idx) = y(end,8);
app.v.CB2Ltot(idx) = y(end,9);
app.v.CAcLtot(idx) = y(end,10);
app.v.CAlLtot(idx) = y(end,11);
app.v.CCLtot(idx)  = y(end,12);
app.v.pH(idx)      = y(end,13);
app.v.xO2(idx)     = y(end,14);
app.v.xCO2(idx)    = y(end,15);
app.v.hF(idx)      = y(end,16);
app.v.AAF(idx)     = y(end,17);
app.v.thetaD(idx)  = y(end,18);
app.v.thetaL(idx)  = y(end,19);
if app.v.thetaL(previdx) > 100.0
    app.v.thetaL(previdx) = 100.0; % Set flag that this happened!
    logMessage(app.Startingscreen, app.projectID, "Temperature >100°C was reached");
end

% Volumetric substrate intake
app.v.QS1in(idx) = (app.v.FR1(previdx)*app.p.cS1R1+app.v.FR2(previdx)*app.p.cS1R2)/app.v.VL(previdx);
app.v.QS2in(idx) = (app.v.FR1(previdx)*app.p.cS2R1+app.v.FR2(previdx)*app.p.cS2R2)/app.v.VL(previdx);

% Measurment data
app.v.pHLm(idx) = meas_transfer_function(app.v.pHL(previdx), app.v.pHLm(previdx), app.p.taupHL, app.a.deltat);
app.v.pO2m(idx) = meas_transfer_function(app.v.pO2(previdx), app.v.pO2m(previdx), app.p.taupO2, app.a.deltat);
app.v.thetaLm(idx) = meas_transfer_function(app.v.thetaL(previdx), app.v.thetaLm(previdx), app.p.tauthetaL, app.a.deltat);
app.v.cS1Lm(idx) = meas_transfer_function(app.v.cS1L(previdx), app.v.cS1Lm(previdx), app.p.taucS1L, app.a.deltat);
app.v.cS2Lm(idx) = meas_transfer_function(app.v.cS2L(previdx), app.v.cS2Lm(previdx), app.p.taucS2L, app.a.deltat);

% Add time to process time
app.t(idx) = app.t(previdx) + app.a.deltat;

% Set Volume Flag if VLmax was reached
if app.v.VL(previdx) >= app.p.VLmax
    app.a.VolumeFlag = 1;
end

% Display error message if VLmax was reached and set VLFlag
% to avoid displaying the message multiple times
if any(app.a.VolumeFlag == 1) && any(app.a.VLflag == 0)
    app.a.VLflag = 1;
    stop(app.Timer);
    msg =  sprintf('VLmax of %g l was reached', app.v.VL(previdx));
    errordlg(msg);
    logMessage(app.Startingscreen, app.projectID, msg)
    %% Add the possibility to add 1 l to VLmax
end

    % Safe new index
    app.nxtidx = idx;

    app_new = app;
end