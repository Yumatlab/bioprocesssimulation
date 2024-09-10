function app_new = Pichia_pastoris(app)
%% Open-loop feed control
% % 

if app.switch_exp || app.switch_pulse
    n = num2str(app.currentReservoir);
    % Define them as zero and change aferwards if switch is on
    app.FR1(end+1) = 0;
    app.FR2(end+1) = 0;
    app.FR3(end+1) = 0;
    if app.switch_exp % Exponential feed phase
        % Check if pump is running
        if app.(['f_FR' n]) == 1
            % Calculate feeding rate FR(t)
            FRwj = app.(['FR' n 'wj']);
            qxpxwj = app.(['qxpxw' n 'j']);
            tj = app.(['t' n 'j']);

            FR = FRwj*exp(qxpxwj*(app.t(end)-tj));
            if FR < app.(['FR' n 'max'])
                app.(['FR' n])(end) = FR;
            else
                msg = sprintf("The desired pumping capacity for FR%i is greater than the maximum pumping capacity.",n);
                fprintf(append(msg,"\n"));
                logMessage(app.CallingApp, msg)
                app.(['f_R' n]) = 0; % Turn pump off
            end
        end
    elseif app.switch_pulse % Pulse feed phase
        % Check if pump is running
        if app.(['f_FR' n]) == 1
            app.(['FR' n])(end) = app.(['FR' n 'max']) * app.(['kR' n]);
        end
    end
    
end

%% pO2 control
            % Check if aeration with pure nitrogen or pure carbon dioxide
            % is turned on
            if app.f_aeration == 1
                if app.f_N2 == 1
                    app.FnN2(end+1) = app.FnN2w;
                else
                    app.FnN2(end+1) = 0;
                end

                if app.f_CO2 == 1
                    app.FnCO2(end+1) = app.FnCO2w;
                else
                    app.FnCO2(end+1) = 0;
                end
            end
            % Calculation of quasi stationary SPC-actual values
            if app.f_pO2_agi == 1

                % Calculate deviation from setpoint
                cEagi             = app.pO2w-app.pO2(end); % Error/Controller difference between measured pO2 and Setpoint e = (w-x)
                T                 = 0.001; % Time delay in h
                app.cE_agi        = (cEagi+T/app.deltat*app.cE_agi)/(T/app.deltat+1); % Error filtered through a time delay of first order with delta t and T = 0.001
                app.ce_agi(end+1) = app.cE_agi/(100-1); % Normalized controller difference e = (w-x)/(w_max-w_min); [-1,+1]

                % Calculate controller gains
                app.cP_agi        = app.ce_agi(end)*app.KP_agi; % P-part of controller with KP = 10.0
                app.cI_agi(end+1) = app.cI_agi(end) + (app.ce_agi(end) + app.ce_agi(end-1)) / 2 * app.deltat * app.KI_agi; % I-part of controller with KI = 1000 and with time increment deltat
                app.cD_agi        = (app.ce_agi(end)-app.ce_agi(end-1))/app.deltat*app.KD_agi; % D-part of controller with KD = 0.015 and with time increment deltat PARAMETER ANGEPASST VON 0.25, DA SONST SCHWINGUNG ZU GROß

                % Calculation of new relative setpoint for agitation
                % speed
                yNSt = app.cP_agi+app.cI_agi(end)+app.cD_agi; % PID sum

                % Define limits for new setpoint
                if yNSt < 0.3
                    yNSt = 0.3;
                elseif yNSt > 1
                    yNSt = 1;
                end

                % Calculation of new agitation speed setpoint [1/min]
                app.NSt(end+1) = yNSt*app.NStmax;

            elseif app.f_pO2_feed == 1

                % Calculate deviation from setpoint
                cEfeed             = app.pO2w-app.pO2(end); % Error/Controller difference between measured pO2 and Setpoint e = (w-x)
                app.cE_feed        = (cEfeed+0.001/app.deltat*app.cE_feed)/(0.001/app.deltat+1); % Filtered error through a PT1 delay with T = 0.001 and deltat
                app.ce_feed(end+1) = app.cE_feed/(100-0); % Normalized controller difference e = (w-x)/(w_max - w_min); [-1,+1]

                % Calculate controller outputs
                app.cP_feed = app.ce_feed(end)*app.KP_feed; % P-part of controller with KP = -2.0
                app.cI_feed = app.cI_feed+(app.ce_feed(end)+app.ce_feed(end-1))/2*app.deltat*app.KI_feed; % I-part of controller with KI = -15.0 and deltat
                app.cD_feed = (app.ce_feed(end)-app.ce_feed(end-1))/app.deltat*app.KD_feed; % D-part of controller with KD = -0.009

                % Calculation of new relative setpoint for feed pump
                % PID sum in percent
                app.yfeed  = ((app.cP_feed+app.cI_feed+app.cD_feed)*100+app.yfeed)/2;

                % Define limits for new setpoint
                if app.yfeed < 0
                    app.yfeed = 0;
                elseif app.yfeed > 100
                    app.yfeed = 100;
                end

                % Calculation of new agitation speed setpoint [l/h]
                app.FR(end+1) = app.yfeed/100*app.FRmax;

            elseif app.f_pO2_aeration == 1

                % Calculate deviation from setpoint
                cEaeration             = app.pO2w-app.pO2(end); % Error/Controller difference between measured pO2 and Setpoint e = (w-x)
                app.cE_aeration        = (cEaeration+0.001/app.deltat*app.cE_aeration)/(0.001/app.deltat+1); % Filtered error through a PT1 delay with T = 0.001 and deltat
                app.ce_aeration(end+1) = app.cE_aeration(end)/(100-1); % Normalized controller difference e = (w-x)/(w_max - w_min); [-1,+1]

                % Calculate controller gains
                app.cP_aeration = app.ce_aeration(end)*app.KP_aeration; % P-part of controller with KP = 20.0
                app.cI_aeration = app.cI_aeration+(app.ce_aeration(end)+app.ce_aeration(end-1))/2*app.deltat*app.KI_aeration; % I-part of controller with KI = 0.003 with time increment 0.005 h
                app.cD_aeration = (app.ce_aeration(end)-app.ce_aeration(end-1))/app.deltat*app.KD_aeration; % D-part of controller with KD = 0.0188

                % Calculation of new setpoint for aeration rate (add O2
                % aeration if AIR aeration is no longer sufficient)
                yaeration  = (app.cP_aeration+app.cI_aeration+app.cD_aeration(end))*100; % PID sum in percent
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
                app.FnAIR(end+1) = yaeration/100*app.FnAIRmax;
                app.FnO2(end+1) = diff/100*app.FnO2max;

                % Calculate overall aeration rate [l/h]
                app.FnG(end+1) = app.FnAIR(end)+app.FnO2(end)+app.FnN2(end)+app.FnCO2(end);

            elseif app.f_pO2_gasmix == 1

                % Calculate deviation from setpoint
                cEgasmix             = app.pO2w-app.pO2(end); % Error/Controller difference between measured pO2 and Setpoint e = (w-x)
                app.cE_gasmix        = (cEgasmix+0.001/app.deltat*app.cE_gasmix)/(0.001/app.deltat+1); % Filtered error through a PT1 delay with T = 0.001 and deltat
                app.ce_gasmix(end+1) = app.cE_gasmix(end)/(1-app.xOAIR); % Normalized controller difference e = (w-x)/(w_max - w_min); [-1,+1]

                app.cP_gasmix        = app.ce_gasmix(end)*app.KP_gasmix; % P-part of controller with KP = 0.4
                app.cI_gasmix(end+1) = app.cI_gasmix(end)+(app.ce_gasmix(end)+app.ce_gasmix(end-1))/2*app.deltat*app.KI_gasmix; % I-part of controller with KI = 0.003 with time increment 0.005 h
                app.cD_gasmix        = (app.ce_gasmix(end)-app.ce_gasmix(end-1))/app.deltat*app.KD_gasmix; % D-part of controller with KD = 0.0005

                % Calculation of new relative setpoint for xOGin
                ygasmix  = (app.cP_gasmix+app.cI_gasmix(end)+app.cD_gasmix(end))*100; % PID sum in percent

                % Define limits for new setpoint
                if ygasmix < app.xOAIR*100
                    ygasmix = app.xOAIR*100;
                elseif ygasmix > 100
                    ygasmix = 100;
                end

                % Calculation of setpoint fir xOGin [-]
                xOGinw = ygasmix/100*1;

                % Calculation of AIR and O2 aeration rates [l/min]
                app.FnAIR(end+1)    = (app.FnGw*(xOGinw-1))/(app.xOAIR-1);
                app.FnO2(end+1)     = app.FnGw-app.FnAIR(end); % HIER NOCHMAL CHECKEN

                % Calculation of overall aeration rate [l/min]
                app.FnG(end+1) = app.FnAIR(end)+app.FnO2(end+1)+app.FnN2(end)+app.FnCO2(end);

            end

            % Set stirrer speed if it is not pO2-controlled [1/min]
            if app.f_pO2_agi ~= 1
                if app.f_motor == 1
                    app.NSt(end+1) = app.NStw;
                else
                    app.NSt(end+1) = 0;
                end
            end

            % Calculation of feed rate with feed pump ON/OFF if it is not pO2-controlled [l/h]
            if app.f_pO2_feed ~= 1
                if app.f_feed == 1
                    app.FR(end+1) = app.FRw;
                else
                    app.FR(end+1) = 0;
                end
            end

            %% Aeration rate

            % Calculate aeration rate [l/min]
            if app.f_pO2_aeration ~= 1 && app.f_pO2_gasmix ~= 1
                if app.f_aeration == 1
                    if app.f_air == 1
                        app.FnAIR(end+1) = app.FnAIRw;
                    else
                        app.FnAIR(end+1) = 0;
                    end

                    if app.f_O2 == 1
                        app.FnO2(end+1) = app.FnO2w;
                    else
                        app.FnAIR(end+1) = 0;
                    end

                    % Total unfiltered aeration rate
                    app.FnG(end+1) = app.FnAIR(end)+app.FnO2(end)+app.FnN2(end)+app.FnCO2(end);
                else
                    app.FnG(end+1)  = 0;
                end
            end

            if app.f_LW_harvest  == 1

                % Calculate difference to setpoint
                cELW             = app.VL(end)*app.rhoL-app.LWw; % Error/Controller difference between measured liquid weight and Setpoint e = (w-x)
                app.cE_LW        = (cELW+0.001/app.deltat*app.cE_LW)/(0.001/app.deltat+1); % Error filtered through a time delay of first order with deltat and T = 0.001 h
                app.ce_LW(end+1) = app.cE_LW/(app.VLmax*app.rhoL-app.VLmin*app.rhoL); % Normalized controller difference e = (w-x)/(w_max - w_min); [-1,+1]

                % Calculate controller gains
                cP_LW            = app.ce_LW(end)*app.KP_LW; % P-part of controller with KP = 10.0
                app.cI_LW(end+1) = app.cI_LW(end)+(app.ce_LW(end)+app.ce_LW(end-1))/2*app.deltat*app.KI_LW; % I-part of controller with KI = 0.3 and with time increment deltat
                cD_LW            = (app.ce_LW(end)-app.ce_LW(end-1))/app.deltat*app.KD_LW; % D-part of controller with KD = 1.0

                % Calculation of new relative setpoint for harvest pump
                yLW  = (cP_LW+app.cI_LW(end)+cD_LW)*100; % PID sum in percent

                % Define limits for new setpoint
                if yLW < 0
                    yLW = 0;
                elseif yLW > 100
                    yLW = 100;
                end

                % Calculation of new setpoint for harvest pump [l/h]
                app.FH(end+1) = yLW/100*app.FHmax;
            else
                % Set harvest rate with harvest pump ON/OFF [l/h]
                if app.f_harvest == 1
                    app.FH(end+1) = app.FHrelw/100*app.FHmax;
                else
                    app.FH(end+1) = 0;
                end
            end

            % Calculate molefraction at reactor inlet [-]
            if app.FnG(end) > 0
                app.xOGin(end+1) = (app.xOAIR*app.FnAIR(end)+app.FnO2(end))/app.FnG(end);
                app.xCGin          = (app.xCAIR*app.FnAIR(end))/app.FnG(end); % CO2 term was deleted as no aeration with CO2 will take place in this simulation
            else
                app.xOGin(end+1) = 0;
                app.xCGin           = 0;
            end

            % Set tONi to time of inoculation, if it has already taken
            % place [h]
            if app.ToI ~= 0
                tONi = app.ToI;
            end

            % Calculate anti foam addition activity
            if app.f_antifoam == 1 && app.ToI ~= 0
                TON   = app.t(end)-tONi;
                AAFin = app.AAFtast*app.VAF^(TON/app.Ttast);
            else
                tONi  = app.t(end);
                AAFin = 0;
                TON   = 0;
            end

            if app.f_pH_mode == 1
                % Calculation of titration rate with alkali pump ON/OFF [l/h]
                if app.f_alkali == 1
                    app.FT2 = app.FT2max;
                else
                    app.FT2 = 0;
                end

                % Calculation of titration rate with acid pump ON/OFF [l/h]
                if app.f_acid == 1
                    app.FT1 = app.FT1max;
                else
                    app.FT1 = 0;
                end
            end

            if app.f_pH_mode == 0
                % Calculation of pH difference to Setpoint and
                % corresponding controller output as setpoint for
                % acid/alkali pumps (Cascade Control)
                if abs(app.pHw-app.pHL(end)) < 0.1
                    app.FT1 = 0;
                    app.FT2 = 0;
                else

                    % Calculate difference to setpoint
                    epH       = app.pHw-app.pHL(end); % Error/Controller difference between pH in Liquid and Setpoint e = (w-x)
                    app.cEpH  = (epH+0.001/app.deltat*app.cEpH)/(0.001/app.deltat+1); % Filtered error through a PT1 delay with T = 0.001 h and deltat
                    cepH      = app.cEpH/(app.pHLmaxgr-app.pHLmingr); % Normalized controller difference e = (w-x) / (w_max - w_min) ; [-1,+1]

                    % Calculate controller gains
                    cP_pH  = cepH*app.KP_pH; % P-part of controller with KP = 10000

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
                    cEypH  = app.ypH_SET-(ypH/100); % Error/Controller difference between measured pH difference to setpoint and wanted difference
                    ceypH  = cEypH/(1-(-1)); % Normalized controller difference if the maximum ypH is 1 and the minimum ypH is -1

                    % Calculation of new setpoint for acid/alkali pump
                    % by slave controller
                    % [l/h]
                    cP_ypH = ceypH*100; % P-part of controller in percent

                    % Calculation of T1 or T2 flow rate
                    % Define limits for new setpoint
                    if cP_ypH > 0
                        yT1 = cP_ypH*app.KP_pH2a;
                        if yT1 > 100
                            yT1 = 100;
                        end
                        app.FT1 = yT1/100*app.FT2max;
                        app.FT2 = 0;
                    elseif cP_ypH < 0
                        yT2 = cP_ypH*app.KP_pH2b;
                        if yT2 > 100
                            yT2 = 100;
                        end
                        app.FT1 = 0;
                        app.FT2 = yT2/100*app.FT1max;
                    else
                        app.FT1 = 0;
                        app.FT2 = 0;
                    end
                end
            end

            if app.f_temp_mode == 1
                % Calculation of cooling power with cooling flux ON/OFF
                % [kg/h]
                if app.f_cooling == 1
                    app.mdotC = app.mdotCmax;
                else
                    app.mdotC = 0;
                end

                % Calculation of heating power with heating rod ON/OFF [W]
                if app.f_heating == 1
                    PH = app.PHmax;
                else
                    PH = 0;
                end
            end

            if app.f_temp_mode == 0
                % Calculation of temperature difference to Setpoint and corresponding controller parameters for temperature control at split range
                % A PT1 controller is used to filter the error signal and dampen its fluctuations
                e              = app.thetaLw-app.thetaL(end); % Error/Controller difference between Temperature in Liquid and Setpoint e = (w-x)
                app.cE         = (e+0.001/app.deltat*app.cE)/(0.001/app.deltat+1); % Filtered error through a PT1 delay with T = 0.001 h and deltat
                app.ce(end+1)  = app.cE/(app.thetaLmaxgr-app.thetaLmingr); % Normalized controller difference e = (w-x) / (w_max - w_min) ; [-1,+1]

                app.cP_Part        = app.ce(end)*app.KP_temp1; % P-part of controller with KP = 0.1
                app.cI_Part(end+1) = app.cI_Part(end)+(app.ce(end)+app.ce(end-1))/2*app.deltat*app.KI_temp1; % I-part of controller with KI = 0.01 with time increment deltat

                % Calculation of steam mass flux and cooling flux in case of steam heating at split-range
                wDJ  = app.cP_Part+app.cI_Part(end)+app.thetaDJ_WP; % PI sum + Workingpoint (ThetaDJw = ThetaLw)

                cDJ  = wDJ-app.thetaDJ; % Error/controller difference between temperature in double jacket and the calculated setpoint cDJ
                CDJ  = cDJ/(100-0); % Normalized controller difference assuming the double jacket should not be cooler than 0°C or hotter than 100°C

                yDJ = CDJ*100; % Master controller output in percent

                % Define limits for new setpoint
                if yDJ > 100
                    yDJ = 100;
                elseif yDJ < -100
                    yDJ = -100;
                end

                if yDJ > 0
                    yH    = yDJ*app.KP_temp2h; % Slave controller output with KP = 10
                    if yH > 100
                        yH = 100;
                    end
                    app.mdotH = (yH/100)*app.mdotHmax;
                    app.mdotC = 0;
                else
                    yC    = -yDJ*app.KP_temp2c; % Slave controller output with KP = -10
                    if yC < -100
                        yC = -100;
                    end
                    app.mdotH = 0;
                    app.mdotC = (yC/100)*app.mdotCmax*10;
                end
            end

            % Eigenvalues of foam and anti foam deq. [1/h]
            lambdaF  = -app.AAF(end)/app.tauF0/(1+app.KFpX*app.cXL(end));
            lambdaAF = -app.cXL(end)/app.KAF;

            %DR  = 0;
            DR1 = 0;
            DR2 = 0;
            DR3 = 0;
            DT1 = 0;
            DT2 = 0;
            if app.VL(end) > 0
                %DR  = app.FR(end)./app.VL(end); % Refered feeding rate [1/h]
                for i = 1:3
                    n = num2str(i);
                    if app.(['f_FR' n]) == 1
                        eval((['DR' n])) = app.(['FR' n])(end)/app.VL(end); % Dilution rate [1/h]
                    end
                end
                DT1 = app.FT1/app.VL(end); % Refered acid titration rate [1/h]
                DT2 = app.FT2/app.VL(end); % Refered alkali titration rate [1/h]
            end
%% Previous method
            % % Define ODE function for volume calculation
            % ODE_Vol       = @(t,yV) ODE_Volume(app.FR(end),app.FH(end),app.FT1,app.FT2,t,yV);
            % 
            % % Liquid volume balance
            % [~,yV] = ode45(ODE_Vol,[0 app.deltat],[app.VL(end) app.VR(end) app.VT2(end) app.VT1(end)]);
            % app.VL(end+1)  = yV(end,1);
            % %app.mLkgEditField.Value = app.VL(end)*app.rhoL;
            % app.VR(end+1)  = yV(end,2);
            % app.VT2(end+1) = yV(end,3);
            % app.VT1(end+1) = yV(end,4);
            % 
            % app.Vfeed(end+1) = app.VR0-app.VR(end);
            % app.Vbase(end+1) = app.VT20-app.VT2(end);
            % app.Vacid(end+1) = app.VT10-app.VT1(end);
            % 
            % % Refered dilution rate [1/h]
            % Din = DR+DT1+DT2;
%% New method
% Define ODE function for volume calculation
            ODE_Vol       = @(t,yV) ODE_Volume_New(app.FR1(end),app.FH(end),app.FT1,app.FT2,t,yV);

            % Liquid volume balance
            [~,yV] = ode45(ODE_Vol,[0 app.deltat],[app.VL(end) app.VR1(end) app.VR2(end) app.VR3(end) app.VT2(end) app.VT1(end)]);
            app.VL(end+1)  = yV(end,1);
            %app.mLkgEditField.Value = app.VL(end)*app.rhoL;
            app.VR1(end+1)  = yV(end,2);
            app.VT2(end+1) = yV(end,5);
            app.VT1(end+1) = yV(end,6);

            app.Vbase(end+1) = app.VT20-app.VT2(end);
            app.Vacid(end+1) = app.VT10-app.VT1(end);

            % Refered dilution rate [1/h]
            Din = DR1+DR2+DR3+DT1+DT2;
            % Temperature liquid phase [K]
            TL  = app.thetaL(end)+app.TnG;

            % Pressure in reactor measured in gas phase [N/m^2]
            if app.thetaL(end) < 100
                app.pG(end+1) = app.pGw;
                %ExppDL        = 0;
                %pDL           = 0;
            else
                ExppDL        = 10.9-2461/TL-2.065*log10(app.thetaL(end)/app.TnG);
                % Steam pressure in liquid phase
                pDL           = 9.8067*10^ExppDL;
                app.pG(end+1) = pDL;
            end

            % Over pressure indication [bar]
            app.deltapG = (app.pG(end)-app.pnG)/10^5;


            % Quasistationary molar respiration quotient (offgas)
            RQ_Z = app.xCO2(end)/100*(1-app.xOGin(end))-app.xCGin*(1-app.xO2(end)/100); % Check if xCGin is correct
            RQ_N = app.xOGin(end)*(1-app.xCO2(end)/100)-app.xO2(end)/100*(1-app.xCGin);
            if RQ_N ~= 0
                app.RQ(end+1) = RQ_Z/RQ_N;
            else
                app.RQ(end+1) = 1;
            end
            if app.RQ(end) <= 0
                app.RQ(end) = 0.0001; % Avoid NaN error for C balance as it requires division by RQ
            end

            % to compare - RQ over metabolism
            % RQ_int = app.yCpO*app.MO2/app.MCO2;

            % Iterative calculation of pH in liquid phase
            % Cations of the bufffer
            y1 = (app.CB1Ltot(end)+2*app.CB2Ltot(end))/app.CH0;

            % Anions of the buffer = total phosphoric acid
            y2 = (app.CB1Ltot(end)+app.CB2Ltot(end))/app.CH0;

            % Dissolved-CO2
            y3 = app.CCLtot(end)/app.CH0;

            % Product acetate
            y4 = app.CPLtot(end)/app.CH0;

            % Titrated base
            y5 = app.CAlLtot(end)/app.CH0;

            % Titrated acid
            y6 = app.CAcLtot(end)/app.CH0;

            % Iterative solution
            xpH    = 10^(7-app.pH(end));
            app.QuotpH = 0.9;

            % Iteration
            for i = 1:100
                if (app.QuotpH <= 0.999 || app.QuotpH >= 1.001) && xpH >= 0 % If xpH < 0 NaN error occurs SET FLAG THIS WOULD HAVE HAPPENED
                    app.xpHkm1 = xpH;
                    fpH0    = xpH^2-1;
                    fpH1    = xpH*y1;
                    fpH2    = -(app.ApH*xpH^2+2*app.BpH*xpH+3*app.CpH)*xpH/(xpH^3+app.ApH*xpH^2+app.BpH*xpH+app.CpH)*y2;
                    fpH3    = -(app.DpH+2*app.EpH/xpH)*y3;
                    fpH4    = -app.FpH*xpH/(app.FpH+xpH)*y4;
                    fpH5    = app.GpH*xpH^2/(1+app.GpH*xpH)*y5;
                    fpH6    = -(app.HpH*xpH+2*app.IpH)*xpH/(xpH^2+app.HpH*xpH+app.IpH)*y6;
                    fpH     = fpH0+fpH1+fpH2+fpH3+fpH4+fpH5+fpH6;
                    fstrpH0 = 2*xpH;
                    fstrpH1 = y1;
                    fstrpH2 = -((app.ApH^2-2*app.BpH)*xpH^4+ ...
                        (2*app.ApH*app.BpH-6*app.CpH)*xpH^3+ ...
                        2*app.BpH^2*xpH^2+4*app.BpH*app.CpH*xpH+ ...
                        3*app.CpH^2)/((xpH^3+app.ApH*xpH^2+app.BpH*xpH+app.CpH)^2)*y2;
                    fstrpH3 = 2*app.EpH/(xpH*xpH)*y3;
                    fstrpH4 = -app.FpH^2/((xpH+app.FpH)^2)*y4;
                    fstrpH5 = app.GpH*xpH*(2+app.GpH*xpH)/((1+app.GpH*xpH)^2)*y5;
                    fstrpH6 = -((app.HpH^2-2*app.IpH)*xpH^2+2*app.HpH*app.IpH*xpH+2*app.IpH^2)/((xpH^2+app.HpH*xpH+app.IpH)^2)*y6;
                    fstrpH  = fstrpH0+fstrpH1+fstrpH2+fstrpH3+fstrpH4+fstrpH5+fstrpH6;
                    xpH     = xpH-fpH/fstrpH;
                    app.QuotpH  = app.xpHkm1/xpH;
                else
                    break
                end
            end

            if xpH < 0
                xpH = -xpH; % Set flag that this occured
            end

            % pH value in liquid phase
            app.pHL(end+1) = 7-log10(xpH);

            % Molar concentration of the H+ ions in the liquid phase
            app.CHL = xpH*app.CH0;
            % Influence of temperature and pH of the growth
            if app.pHL(end) >= app.thetaLmingr && app.pHL(end) <= app.pHLmaxgr
                fpH    = (app.pHL(end)-app.pHLmingr)*(app.pHL(end)-app.pHLmaxgr)/((app.pHL(end)-app.pHLmingr)*(app.pHL(end)-app.pHLmaxgr)-(app.pHL(end)-app.pHLoptgr)^2);
            else
                fpH    = 0;
            end
            if app.thetaL(end) >= app.thetaLmingr && app.thetaL(end) <= app.thetaLmaxgr
                ftheta = ((app.thetaL(end)-app.thetaLmaxgr)*(app.thetaL(end)-app.thetaLmingr)^2)/((app.thetaLoptgr-app.thetaLmingr)*((app.thetaLoptgr-app.thetaLmingr)*(app.thetaL(end)-app.thetaLoptgr)-(app.thetaLoptgr-app.thetaLmaxgr)*(app.thetaLoptgr+app.thetaLmingr-2*app.thetaL(end))));
            else
                ftheta = 0;
            end

            % Maximum specific growth rate glucose [1/h]
            my1max = app.my1opt*fpH*ftheta;

            % Maximum specific growth rate glycerol [1/h]
            my2max = app.my2opt*fpH*ftheta;

            % Maximum specific growth rate acetate [1/h]
            my3max = app.my3opt*fpH*ftheta;

            % Maximum specific glucose uptake rate [1/h]
            app.qS1pXmax = (my1max+app.mySm)/app.yXpS1gr;

            % Maximum specific glycerol uptake rate [1/h]
            app.qS2pXmax = (my2max+app.mySm)/app.yXpS2gr;

            % Maximum specific acetate uptake rate [1/h]
            app.qS3pXmax = (my3max+app.mySm)/app.yXpS3gr;

            % Maximum specific oxygen uptake rate [1/h]
            app.qOpXmax  = (my1max+app.mySm)/app.yXpOgr+app.qOpXm;

            % Calculation of O2 quantities
            % Maintenance O2 uptake rate [1/h]
            app.OURm(end+1)    = app.qOpXm*app.cXL(end);

            % Maximum O2 uptake rate [1/h]
            app.OURmax(end+1)  = app.qOpXmax*app.cXL(end);

            % Calculation of O2 Henry constant [Nm/kg]
            app.HO2 = app.HnO2/(1+app.K1HO2*app.thetaL(end)+app.K2HO2*app.thetaL(end)^2+app.K3HO2*app.thetaL(end)^3+app.K4HO2*app.thetaL(end)^4);

            % O2-concentration in liquid phase at 100 % pO2-indication
            app.cOL100 = app.pGcal*app.xOGcal/app.HO2;

            % Maximum potential O2 concentration in liquid phase [g/l]
            app.cOLmax = app.pG(end)/app.HO2;

            % Maximum oxygen supply rate [g/(l*h)]
            if app.VL(end) > 0
                app.QO2max(end+1) = app.FnG(end)*60*app.MO2/(app.VnM*app.VL(end));
            else
                app.QO2max(end+1) = 0;
            end

            % Maximum CO2 supply rate [g/(l*h)]
            app.QCO2max(end+1) = app.QO2max(end)*app.MCO2/app.MO2;

            % Calculation of viscosity [Ns/m^2]
            eta = app.etaXL*(app.etaH2O/app.etaXL)^(app.cXL(end)/app.cXLeta);

            % Volume refered O2-transition coefficient kLa [1/h]
            VLwert         = (app.VL(end)/app.VLmin)^app.alpha;
            NStwert        = (app.NSt(end)/app.NStmax)^(3*app.alpha);
            FGwert         = (app.FnG(end)/app.FnGmax)^app.beta;
            etawert        = (eta/app.etaH2O)^app.gamma;

            app.kLa(end+1) = app.kLamin+app.kLamax*FGwert*NStwert/VLwert*etawert*(1-app.AAF(end));

            % Theoretical maximum O2 transfer rate [g/(l*h)]
            app.OTRmax(end+1)  = app.kLa(end)*app.cOLmax;

            % Calculation of Stanton coefficient of oxygen
            if app.QO2max(end) > 0
                StO = app.OTRmax(end)/app.QO2max(end);
            else
                StO = 10^20;
            end

            % Optimum O2 limiting transport rate
            % OTRopt = app.OTRmax(end)/(1+StO);

            % O2-pulp quantity in reactor liquid phase
            app.xOL(end+1) = app.cOL(end)/app.cOLmax;

            % OTR [g/(l*h)]
            app.OTR(end+1) = app.OTRmax(end)*(app.xOGin(end)-app.xOL(end))*2/((1+StO-(1-app.RQ(end))*StO*app.xOL(end))+sqrt((1+StO-(1-app.RQ(end))*StO*app.xOL(end))^2-4*(1-app.RQ(end))*StO*(app.xOGin(end)-app.xOL(end))));
            if app.OTR(end) < 0
                app.OTR(end) = 0;
            end

            % Calculation of quasistationary O2 gas phase mole fraction [-]
            if app.OTR(end) ~= 0
                app.xOG(end+1) = (app.QO2max(end)*app.xOGin(end)-app.OTR(end))/(app.QO2max(end)-(1-app.RQ(end))*app.OTR(end));
            else
                app.xOG(end+1) = app.xOGin(end);
            end

            % Calculation of CO2 Herny constant [Nm/kg]
            app.HCO2 = app.HnCO2/(1+app.K1HCO2*app.thetaL(end)+app.K2HCO2*app.thetaL(end)^2+app.K3HCO2*app.thetaL(end)^3+app.K4HCO2*app.thetaL(end)^4);

            % Maximum CO2 concentration [g/l]
            app.cCLmax = app.pG(end)/app.HCO2;

            % Dissolved CO2-concentration in liquid phase [g/l]
            app.cCL = (app.CHL^2*app.MCO2*app.CCLtot(end))/(app.CHL^2+app.KC1*app.CHL+app.KC1*app.KC2);

            % CO2-pulp quantity in reactor liquid phase [-]
            app.xCL = app.cCL/app.cCLmax;

            % Theoretical maximum CO2 transfer rate [g/(l*h)]
            app.CTRmax = app.deltaCpO*app.kLa(end)*app.cCLmax;

            % Stanton coefficient of CO2
            if app.QCO2max(end) > 0
                app.StC = app.CTRmax/app.QCO2max(end);
            else
                app.StC = 10^20;
            end

            % CO2 transfer rate
            app.CTR(end+1) = app.CTRmax*(app.xCGin-app.xCL)*2/((1+app.StC-(1-1/app.RQ(end))*app.StC*app.xCL)+sqrt((1+app.StC-(1-1/app.RQ(end))*app.StC*app.xCL)^2-4*(1-1/app.RQ(end))*app.StC*(app.xCGin-app.xCL)));

            % Calculation of the quasistationary CO2 gas phase mole fraction
            app.xCG(end+1) = (app.QCO2max(end)*app.xCGin-app.CTR(end))/(app.QCO2max(end)-(1-1/app.RQ(end))*app.CTR(end));

            % Optimum specific substrate uptake rate (no O2 limitation) [1/h]
            if app.cS1L(end) <= 0
                qS1pXopt = 0;
            else
                qS1pXopt = app.qS1pXmax*app.cS1L(end)/(app.cS1L(end)+app.kS1);
            end

            % Optimum specific substrate uptake rate 2 [1/h]
            if app.cS2L(end) <= 0
                qS2pXopt = 0;
            else
                qS2pXopt = app.qS2pXmax*app.cS2L(end)/(app.cS2L(end)+app.kS2)*app.kI21/(app.cS1L(end)+app.kI21);
            end

            % Share of substrate 3 of the product
            if app.CPLtot(end) <= 0
                app.cS3L(end+1) = 0;
            else
                app.cS3L(end+1) = app.CPLtot(end)*app.MP;
            end

            % Optimum specific substrate uptake rate 3 [1/h]
            if app.cS3L(end) <= 0
                qS3pXopt = 0;
            else
                qS3pXopt = app.qS3pXmax*app.cS3L(end)/(app.cS3L(end)+app.kS3)*app.kI31/(app.cS1L(end)+app.kI31)*app.kI32/(app.cS2L(end)+app.kI32);
            end

            % Specific cell growth rate at substrate limitation
            qXpXSgr = app.yXpS1gr*qS1pXopt+app.yXpS2gr*qS2pXopt+app.yXpS3gr*qS3pXopt;

            % Specific cell growth rate at O2 limitation
            if app.cOL(end) <= 0
                qXpXOgr = 0;
            else
                qXpXOgr = app.yXpOgr*(app.qOpXmax-app.qOpXm)*app.cOL(end)/(app.kO+app.cOL(end));
            end

            % Specific cell growth rate
            if qXpXSgr < qXpXOgr
                qXpXgr = qXpXSgr;
                if any(app.f_Inoc == 1)
                    %   app.LimitationTypeLabel.Text = "Substrate Limitation";
                end
            else
                qXpXgr = qXpXOgr;
                if any(app.f_Inoc == 1)
                    %   app.LimitationTypeLabel.Text = "Oxygen Limitation";
                end
            end

            % Calculation of cell specific reaction rates
            % Specific cell reaction rate
            if any(app.f_Inoc == 1)
                app.qXpX(end+1) = qXpXgr-app.mySm;
            else
                app.qXpX(end+1) = 0;
            end
            % app.qXpX1hEditField.Value = app.qXpX(end);

            % Specific substrate uptake rate glucose [1/h]
            SSG = qXpXgr/app.yXpS1gr;
            if SSG < qS1pXopt
                qS1pX = SSG;
            else
                qS1pX = qS1pXopt;
            end

            % Specific substrate uptake rate glycerine [1/h]
            SSGl = (qXpXgr-app.yXpS1gr*qS1pX)/app.yXpS2gr;
            if SSGl < qS2pXopt
                qS2pX = SSGl;
            else
                qS2pX = qS2pXopt;
            end

            % Specific substrate uptake rate acetate [1/h]
            SSA = (qXpXgr-app.yXpS1gr*qS1pX-app.yXpS2gr*qS2pX)/app.yXpS3gr;
            if SSA < qS3pXopt
                qS3pX = SSA;
            else
                qS3pX = qS3pXopt;
            end

            % Specific ammonia uptake rate [1/h]
            qAlpX = app.yAlpXgr*qXpXgr;

            % Specific uptake rate of titrated acid [1/h]
            qAcpX = app.yAcpXgr*qXpXgr;

            % Specific oxygen uptake rate [1/h]
            qOpX = qXpXgr/app.yXpOgr+app.qOpXm;

            % Resulting O2 yield coeficient
            %yXpO = app.yXpOgr*app.qXpX(end)/(app.qXpX(end)+app.myOm);

            % Volumetric oxygen uptake rate [g/(l*h)] and kLa [1/h]
            if any(app.f_Inoc == 1)
                app.OUR(end+1) = qOpX*app.cXL(end);
            else
                app.OUR(end+1) = 0;
            end

            % Volumetric oCO2 production rate [g/(l*h)]
            CER = app.yCpO*app.OUR(end);

            % Specific production rate, S-limited, O2-inhibited [1/h]
            qPpX = (app.yPpS1*qS1pXopt+app.yPpS2*qS2pXopt)*app.kIPO/(app.kIPO+app.cOL(end))-app.yPpS3*qS3pX;

            % Calculation of ammonia transfer rate (volatile) [g/(l*h)]
            AlTR = -app.KAlvol*app.FnG(end)*app.CAlLtot(end)*app.MAl/app.VL(end);

            % Calculation of variables in the temperature systems
            % Quasitationary calculation of the heat exchanger
            % temperature
            % Dilution rate of the steam flux [1/h]
            if app.f_temp_mode == 0
                DH = app.mdotH/app.mHmax;
            end

            % Time constant of the primary heating cycle [h]
            tauHTh = app.mHmax*app.cH2O/(app.kHTh*app.AHTh);

            % Dimensionless quantities
            if app.f_temp_mode == 0
                phiHTh = DH*tauHTh;
                phiHT  = app.mdotH/app.mdotT;
            end

            % Temperature of heating outlet
            % Electrical heating [°C]
            if app.f_temp_mode == 1
                if app.f_heating == 1
                    app.thetaTh = app.thetaD(end)+app.RT*PH;
                else
                    app.thetaTh = app.thetaL(end); % Added this line to account for thetaTh when the heating power is turned off
                end
            end

            % Steam heating as alternative for electrical heating
            if app.f_temp_mode == 0
                app.thetaTh = ((1+phiHTh)*app.CHmax*app.thetaD(end)+phiHT*(app.CHmax*app.thetaHin+app.Qny(end)))/(app.CHmax*(1+phiHTh+phiHT));
            end

            % Dilution rate of cooling flux [1/h]
            DC     = app.mdotC/app.mC;
            phiCTc = DC*app.tauCTc;

            % Cooling outlet temperature [°C]
            app.thetaTc = (phiCTc*app.thetaCin+(1+phiCTc)*app.phiTcC*app.thetaTh)/((1+app.phiTcC)*(1+phiCTc)-1);

            % Cooling water outlet temperature [°C]
            app.thetaC  = (phiCTc*app.thetaCin+app.thetaTc)/(1+phiCTc);

            % Cascade control quantity
            app.thetaDJ = app.thetaTc;

            % Volumetric heat capacity of the liquid ohase and share of
            % the wall [Wh/K]
            CL = app.rhoL*app.VL(end)*app.cH2O+app.mWL*app.cW;

            % Time constant liquid phase - double jacket [h]
            tauLD = CL/(app.kDL*app.ADL);

            % Time constant liquid phase - environment [h]
            tauLU = CL/(app.kLU*app.ALU);

            % Time constnat reactor liquid phase [h]
            tauL = 1/(1/tauLD+1/tauLU);

            % Microbiological heat generation [W]
            QdotM = app.KHM*app.VL(end)*app.OUR(end);

            % Thermal efficiency of the stirrer
            QdotSt = app.KHSt*app.VL(end)*app.NSt(end)^3;

            % DEFINITION OF DYNAMIC MODEL EQUATIONS
            % Cell mass balances and inoculation
            ODE_concbal = @(t,y) ODE_Luttmann_complete_New(app.qXpX(end),Din,app.cS1R,qS1pX,app.cS2R,qS2pX,app.CPRtot,qPpX,app.MP,app.cOT1,app.cOT2,app.cOR,app.OTR(end),app.OUR(end),app.cOL100,app.TMpO2,DT1,app.CAcT1tot,qAcpX,app.MAc,DT2,app.CAlT2tot,qAlpX,AlTR,app.MAl,DR1,app.CCRtot,app.CCT1tot,app.CCT2tot,app.CTR(end),CER,app.MCO2,app.pHL(end),app.TMpH,app.TMxO2,app.xOG(end),app.TMxCO2,app.xCG(end),lambdaF,app.qhpX,lambdaAF,AAFin,app.tauD,app.DD,app.thetaTc,app.tauDL,app.thetaU,app.tauDU,tauL,tauLD,tauLU,QdotM,QdotSt,CL,t,y);


            % if all(app.inoculum == 0) || any(app.inoc_occ == 1)
            [~,y] = ode45(ODE_concbal,[0 app.deltat],[app.cXL(end) app.cS1L(end) app.cS2L(end) app.CPLtot(end) app.cOL(end) app.pO2(end) app.CB1Ltot(end) app.CB2Ltot(end) app.CAcLtot(end) app.CAlLtot(end) app.CCLtot(end) app.pH(end) app.xO2(end) app.xCO2(end) app.hF(end) app.AAF(end) app.thetaD(end) app.thetaL(end)]);
            % all y values can not be smaller than 0
            for i = 1:18
                if y(end,i) < 0
                    y(end,i) = 0;
                end
            end
            % Check if inoculation occured
            if app.f_Inoc == 1 && app.inoc_occ == 0
                app.cXL(end+1) = app.cXL0; % [g/l]
                app.ToI        = app.t(end);
                app.inoc_occ   = 1;
                logMessage(app.CallingApp, app.projectID, "Inoculation occured")
            else
                app.cXL(end+1)    = y(end,1);
            end
            app.cS1L(end+1)   = y(end,2);
            app.cS2L(end+1)   = y(end,3);
            app.CPLtot(end+1) = y(end,4);
            app.cOL(end+1)    = y(end,5);
            app.pO2(end+1)    = y(end,6);
            app.CB1Ltot(end+1) = y(end,7);
            app.CB2Ltot(end+1) = y(end,8);
            app.CAcLtot(end+1) = y(end,9);
            app.CAlLtot(end+1) = y(end,10);
            app.CCLtot(end+1)  = y(end,11);
            app.pH(end+1)      = y(end,12);
            app.xO2(end+1)     = y(end,13);
            app.xCO2(end+1)    = y(end,14);
            app.hF(end+1)      = y(end,15);
            app.AAF(end+1)     = y(end,16);
            app.thetaD(end+1)  = y(end,17);
            app.thetaL(end+1)  = y(end,18);
            if app.thetaL(end) > 100.0
                app.thetaL(end) = 100.0; % Set flag that this happened!
                logMessage(app.CallingApp, app.projectID, "Temperature >100°C was reached");
            end

            % Measurment data
            app.pHLm(end+1) = meas_transfer_function(app.pHL(end), app.pHLm(end), 20, app.deltat);
            app.pO2m(end+1) = meas_transfer_function(app.pO2(end), app.pO2m(end), 25, app.deltat);
            app.thetaLm(end+1) = meas_transfer_function(app.thetaL(end), app.thetaLm(end), 20, app.deltat);
            % Add time to process time
            app.t(end+1) = app.t(end) + app.deltat;

            % Set Volume Flag if VLmax was reached
            if app.VL(end) >= app.VLmax
                app.VolumeFlag = 1;
            end

            % Display error message if VLmax was reached and set VLFlag
            % to avoid displaying the message multiple times
            if any(app.VolumeFlag == 1) && any(app.VLflag == 0)
                app.VLflag = 1;
                stop(app.Timer);
                msg =  sprintf('VLmax of %g l was reached', app.VL);
                errordlg(msg);
                logMessage(app.CallingApp, app.projectID, msg)
                %  app.PauseButton.Text = "Resume";
                %% Add the possibility to add 1 l to VLmax
            end

            app_new = app;
end