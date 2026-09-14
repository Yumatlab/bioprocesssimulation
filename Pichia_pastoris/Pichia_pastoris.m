function app_new = Pichia_pastoris(app)

% Append the current index by 1
previdx = app.nxtidx;  % previous index
idx     = previdx + 1;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Feeding
% Two reservoirs: R1 = glycerol, R2 = methanol

app.v.FR1(idx) = 0;
app.v.FR2(idx) = 0;

if app.switch_exp
    %% Exponential feed phase — reservoir selected by app.p.R_feed
    k     = num2str(app.p.R_feed);
    FRwj  = app.p.(['FR' k 'j']);
    qxpxw = app.p.(['qXpX' k 'w']);
    tj    = app.p.(['t' k 'j']);
    FR    = FRwj * exp(qxpxw * (app.v.t(previdx) - tj));
    if FR < app.p.(['FR' k 'max'])
        app.v.(['FR' k])(idx) = FR;
    else
        msg = sprintf('Desired pump capacity for FR%s exceeds maximum.', k);
        fprintf('%s\n', msg);
        logMessage(app, 'Phase Information', msg);
        app.switch_exp = false;
    end

elseif app.switch_pulse
    %% Pulse feed phase
    k = num2str(app.p.R_feed);
    app.v.(['FR' k])(idx) = app.p.(['FR' k 'max']) * app.p.(['kR' k]);

elseif app.p.Mode_pO2 == 4
    %% pO2-controlled feed (reservoir 1 as default)
    cEfeedpO2           = app.p.pO2w - app.v.pO2(previdx);
    app.a.cE_feedpO2    = (cEfeedpO2 + 0.001/app.a.deltat*app.a.cE_feedpO2) / ...
                          (0.001/app.a.deltat + 1);
    app.a.ce_feedpO2(idx) = app.a.cE_feedpO2 / (100 - 0);

    app.a.cP_feedpO2 = app.a.ce_feedpO2(previdx) * app.p.KP_feedpO2;
    app.a.cI_feedpO2 = app.a.cI_feedpO2 + ...
        (app.a.ce_feedpO2(previdx) + app.a.ce_feedpO2(end-1)) / 2 * ...
        app.a.deltat * app.p.KI_feedpO2;
    app.a.cD_feedpO2 = (app.a.ce_feedpO2(previdx) - app.a.ce_feedpO2(end-1)) / ...
        app.a.deltat * app.p.KD_feedpO2;

    app.a.yfeedpO2 = ((app.a.cP_feedpO2 + app.a.cI_feedpO2 + ...
        app.a.cD_feedpO2) * 100 + app.a.yfeedpO2) / 2;
    app.a.yfeedpO2 = max(0, min(100, app.a.yfeedpO2));

    app.v.FR1(idx) = app.a.yfeedpO2 / 100 * app.p.FR1max;

elseif app.p.f_feed == 1
    %% Manual or closed-loop feed control for selected reservoir
    n = num2str(app.p.R_feed);
    if app.p.Mode_feed == 0
        % Constant feed
        app.v.(['FR' n])(idx) = app.p.(['FR' n 'w']);
    elseif app.p.Mode_feed == 1
        % Closed-loop substrate concentration control
        cSLw    = app.p.(['cS' n 'Lw']);
        cSL     = app.v.(['cS' n 'Lm'])(previdx);
        cSLwmax = app.p.(['cS' n 'R' n]) * 0.2;
        cSLwmin = 0.01;

        cEfeedR = cSLw - cSL;
        T       = 0.001;
        app.a.(['cE_feedR' n]) = (cEfeedR + T/app.a.deltat * ...
            app.a.(['cE_feedR' n])) / (T/app.a.deltat + 1);
        app.a.(['ce_feedR' n])(idx) = app.a.(['cE_feedR' n]) / ...
            (cSLwmax - cSLwmin);

        app.a.(['cP_feedR' n]) = app.a.(['ce_feedR' n])(previdx) * ...
            app.p.(['KP_feedR' n]);
        app.a.(['cI_feedR' n]) = app.a.(['cI_feedR' n]) + ...
            (app.a.(['ce_feedR' n])(previdx) + app.a.(['ce_feedR' n])(end-1)) / 2 * ...
            app.a.deltat * app.p.(['KI_feedR' n]);
        app.a.(['cD_feedR' n]) = (app.a.(['ce_feedR' n])(previdx) - ...
            app.a.(['ce_feedR' n])(end-1)) / app.a.deltat * app.p.(['KD_feedR' n]);

        yFR = app.a.(['cP_feedR' n]) + app.a.(['cI_feedR' n]) + ...
              app.a.(['cD_feedR' n]);
        yFR = max(0, min(1, yFR));
        app.v.(['FR' n])(idx) = app.p.(['FR' n 'max']) * yFR;
    end
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% pO2 Control

% N2 and CO2 aeration flags
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

switch app.p.Mode_pO2
    case 1  % pO2 agitation control
        cEagi           = app.p.pO2w - app.v.pO2(previdx);
        T               = 0.001;
        app.a.cE_agi    = (cEagi + T/app.a.deltat * app.a.cE_agi) / ...
                          (T/app.a.deltat + 1);
        app.a.ce_agi(idx) = app.a.cE_agi / (100 - 1);

        app.a.cP_agi = app.a.ce_agi(previdx) * app.p.KP_agi;
        app.a.cI_agi = app.a.cI_agi + ...
            (app.a.ce_agi(previdx) + app.a.ce_agi(end-1)) / 2 * ...
            app.a.deltat * app.p.KI_agi;
        % D-on-measurement to avoid derivative kick
        app.a.cD_agi = -app.p.KD_agi * ...
            (app.v.pO2(previdx) - app.v.pO2(max(previdx-1,1))) / app.a.deltat;

        yNSt = app.a.cP_agi + app.a.cI_agi + app.a.cD_agi;
        yNSt = max(0.3, min(1, yNSt));
        app.a.cI_agi = max(0, min(app.a.cI_agi, app.p.NStmax));  % Anti-windup
        app.v.NSt(idx) = yNSt * app.p.NStmax;

    case 2  % pO2 aeration control
        cEaeration           = app.p.pO2w - app.v.pO2(previdx);
        app.a.cE_aeration    = (cEaeration + 0.001/app.a.deltat * ...
            app.a.cE_aeration) / (0.001/app.a.deltat + 1);
        app.a.ce_aeration(idx) = app.a.cE_aeration / (100 - 1);

        app.a.cP_aeration = app.a.ce_aeration(previdx) * app.p.KP_aeration;
        app.a.cI_aeration = app.a.cI_aeration + ...
            (app.a.ce_aeration(idx) + app.a.ce_aeration(previdx)) / 2 * ...
            app.a.deltat * app.p.KI_aeration;
        app.a.cD_aeration = (app.a.ce_aeration(idx) - ...
            app.a.ce_aeration(previdx)) / app.a.deltat * app.p.KD_aeration;

        yaeration = (app.a.cP_aeration + app.a.cI_aeration + ...
            app.a.cD_aeration) * 100;
        diff = 0;
        if yaeration < 30
            yaeration = 30;
        elseif yaeration > 100
            diff      = min(yaeration - 100, 100);
            yaeration = 100;
        end
        app.v.FnAIR(idx) = yaeration / 100 * app.p.FnAIRmax;
        app.v.FnO2(idx)  = diff / 100 * app.p.FnO2max;
        app.v.FnG(idx)   = app.v.FnAIR(previdx) + app.v.FnO2(previdx) + ...
            app.v.FnN2(previdx) + app.v.FnCO2(previdx);

    case 3  % pO2 gas mix control
        cEgasmix         = app.p.pO2w - app.v.pO2(previdx);
        app.a.cE_gasmix  = (cEgasmix + 0.001/app.a.deltat * ...
            app.a.cE_gasmix) / (0.001/app.a.deltat + 1);
        app.a.ce_gasmix(idx) = app.a.cE_gasmix / (1 - app.p.xOAIR);

        app.a.cP_gasmix    = app.a.ce_gasmix(previdx) * app.p.KP_gasmix;
        app.a.cI_gasmix(idx) = app.a.cI_gasmix(previdx) + ...
            (app.a.ce_gasmix(previdx) + app.a.ce_gasmix(end-1)) / 2 * ...
            app.a.deltat * app.p.KI_gasmix;
        app.a.cD_gasmix    = (app.a.ce_gasmix(previdx) - ...
            app.a.ce_gasmix(end-1)) / app.a.deltat * app.p.KD_gasmix;

        ygasmix = (app.a.cP_gasmix + app.a.cI_gasmix(previdx) + ...
            app.a.cD_gasmix) * 100;
        ygasmix = max(app.p.xOAIR * 100, min(100, ygasmix));
        xOGinw  = ygasmix / 100;

        app.v.FnAIR(idx) = (app.p.FnGw * (xOGinw - 1)) / (app.p.xOAIR - 1);
        app.v.FnO2(idx)  = app.p.FnGw - app.v.FnAIR(previdx);
        app.v.FnG(idx)   = app.v.FnAIR(previdx) + app.v.FnO2(previdx) + ...
            app.v.FnN2(previdx) + app.v.FnCO2(previdx);
end

% Stirrer speed if not pO2-controlled
if app.p.Mode_pO2 ~= 1
    if app.p.f_motor == 1
        app.v.NSt(idx) = app.p.NStw;
    else
        app.v.NSt(idx) = 0;
    end
end

% Manual aeration rate (modes 0/1 only)
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
            app.v.FnO2(idx) = 0;
        end
        app.v.FnG(idx) = app.v.FnAIR(previdx) + app.v.FnO2(previdx) + ...
            app.v.FnN2(previdx) + app.v.FnCO2(previdx);
    else
        app.v.FnG(idx) = 0;
    end
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Liquid Weight Control

if app.p.Mode_harvest == 1
    cELW           = app.v.VL(previdx) * app.p.rhoL - app.p.LWw;
    app.a.cE_LW    = (cELW + 0.001/app.a.deltat * app.a.cE_LW) / ...
                     (0.001/app.a.deltat + 1);
    app.a.ce_LW(idx) = app.a.cE_LW / ...
        (app.p.VLmax * app.p.rhoL - app.p.VLmin * app.p.rhoL);

    cP_LW            = app.a.ce_LW(idx) * app.p.KP_LW;
    app.a.cI_LW(idx) = app.a.cI_LW(previdx) + ...
        (app.a.ce_LW(idx) + app.a.ce_LW(previdx)) / 2 * ...
        app.a.deltat * app.p.KI_LW;
    cD_LW            = (app.a.ce_LW(idx) - app.a.ce_LW(previdx)) / ...
        app.a.deltat * app.p.KD_LW;

    yLW = (cP_LW + app.a.cI_LW(idx) + cD_LW) * 100;
    yLW = max(0, min(100, yLW));
    app.v.FH(idx) = yLW / 100 * app.p.FHmax;
else
    if app.p.f_harvest == 1
        app.v.FH(idx) = app.p.FHrelw / 100 * app.p.FHmax;
    else
        app.v.FH(idx) = 0;
    end
end

% Mole fraction at reactor inlet [-]
if app.v.FnG(idx) > 0
    app.v.xOGin(idx) = (app.p.xOAIR * app.v.FnAIR(idx) + ...
        app.v.FnO2(idx)) / app.v.FnG(idx);
else
    app.v.xOGin(idx) = 0;
end

% Anti-foam addition
if app.a.ToI ~= 0
    tONi = app.a.ToI;
end
if app.p.f_antifoam == 1 && app.a.ToI ~= 0
    TON   = app.v.t(previdx) - tONi;
    AAFin = app.p.AAFtast * app.p.VAF^(TON / app.p.Ttast);
else
    tONi  = app.v.t(previdx);
    AAFin = 0;
    TON   = 0;  %#ok<NASGU>
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% pH Control (Manual)

if app.p.Mode_pH == 0
    if app.p.f_alkali == 1
        app.v.FT2(idx) = app.p.FT2max;
    else
        app.v.FT2(idx) = 0;
    end
    if app.p.f_acid == 1
        app.v.FT1(idx) = app.p.FT1max;
    else
        app.v.FT1(idx) = 0;
    end
end

%% pH Control (Auto)
if app.p.Mode_pH == 1
    if abs(app.p.pHw - app.v.pHL(previdx)) < 0.1
        app.v.FT1(idx) = 0;
        app.v.FT2(idx) = 0;
    else
        epH        = app.p.pHw - app.v.pHL(previdx);
        app.a.cEpH = (epH + 0.001/app.a.deltat * app.a.cEpH) / ...
                     (0.001/app.a.deltat + 1);
        cepH       = app.a.cEpH / (app.p.pHLmaxgr - app.p.pHLmingr);

        cP_pH = cepH * app.p.KP_pH;
        ypH   = max(-100, min(100, cP_pH * 100));

        cEypH  = app.p.ypH_SET - (ypH / 100);
        ceypH  = cEypH / (1 - (-1));
        cP_ypH = ceypH * 100;

        if cP_ypH > 0
            yT1 = min(100, cP_ypH * app.p.KP_pH2a);
            app.v.FT1(idx) = yT1 / 100 * app.p.FT2max;
            app.v.FT2(idx) = 0;
        elseif cP_ypH < 0
            yT2 = min(100, cP_ypH * app.p.KP_pH2b);
            app.v.FT1(idx) = 0;
            app.v.FT2(idx) = yT2 / 100 * app.p.FT1max;
        else
            app.v.FT1(idx) = 0;
            app.v.FT2(idx) = 0;
        end
    end
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Temperature Control (Manual)

if app.p.Mode_temp == 0
    if app.p.f_cooling == 1
        app.p.mdotC = app.p.mdotCmax;
    else
        app.p.mdotC = 0;
    end
    if app.p.f_heating == 1
        PH = app.p.PHmax;
    else
        PH = 0;
    end

%% Temperature Control (Auto)
elseif app.p.Mode_temp == 1
    e             = app.p.thetaLw - app.v.thetaL(previdx);
    app.a.cE      = (e + 0.001/app.a.deltat * app.a.cE) / ...
                    (0.001/app.a.deltat + 1);
    app.a.ce(idx) = app.a.cE / (app.p.thetaLmaxgr - app.p.thetaLmingr);

    app.a.cP_Part        = app.a.ce(idx) * app.p.KP_temp1;
    app.a.cI_Part(idx)   = app.a.cI_Part(previdx) + ...
        (app.a.ce(idx) + app.a.ce(previdx)) / 2 * ...
        app.a.deltat * app.p.KI_temp1;

    wDJ = app.a.cP_Part + app.a.cI_Part(idx) + app.p.thetaDJ_WP;
    cDJ = wDJ - app.a.thetaDJ;
    CDJ = cDJ / (100 - 0);
    yDJ = max(-100, min(100, CDJ * 100));

    if yDJ > 0
        yH          = min(100, yDJ * app.p.KP_temp2h);
        app.p.mdotH = (yH / 100) * app.p.mdotHmax;
        app.p.mdotC = 0;
    else
        yC          = min(100, -yDJ * app.p.KP_temp2c);
        app.p.mdotH = 0;
        app.p.mdotC = (yC / 100) * app.p.mdotCmax * 10;
    end
end

% Foam eigenvalues [1/h]
lambdaF  = -app.v.AAF(previdx) / app.p.tauF0 / ...
            (1 + app.p.KFpX * app.v.cXL(previdx));
lambdaAF = -app.v.cXL(previdx) / app.p.KAF;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Volume ODE — 5 states: VL, VR1, VR2, VT2, VT1

DR1 = 0;
DR2 = 0;
DT1 = 0;
DT2 = 0;
if app.v.VL(previdx) > 0
    if app.v.FR1(previdx) > 0
        DR1 = app.v.FR1(previdx) / app.v.VL(previdx);
    end
    if app.v.FR2(previdx) > 0
        DR2 = app.v.FR2(previdx) / app.v.VL(previdx);
    end
    DT1 = app.v.FT1(previdx) / app.v.VL(previdx);
    DT2 = app.v.FT2(previdx) / app.v.VL(previdx);
end

ODE_Vol = @(t,yV) Pichia_ODE_Volume( ...
    app.v.FR1(previdx), app.v.FR2(previdx), ...
    app.v.FH(previdx),  app.v.FT1(previdx), app.v.FT2(previdx), t, yV);

[~,yV] = ode15s(ODE_Vol, [0 app.a.deltat], [ ...
    app.v.VL(previdx)  app.v.VR1(previdx) app.v.VR2(previdx) ...
    app.v.VT2(previdx) app.v.VT1(previdx)]);

app.v.VL(idx)  = yV(end,1);
app.v.VR1(idx) = yV(end,2);
app.v.VR2(idx) = yV(end,3);
app.v.VT2(idx) = yV(end,4);
app.v.VT1(idx) = yV(end,5);

app.v.VR1in(idx) = app.p.VR10 - app.v.VR1(previdx);  % Glycerol added
app.v.VR2in(idx) = app.p.VR20 - app.v.VR2(previdx);  % Methanol added
app.v.Vbase(idx) = app.p.VT20 - app.v.VT2(previdx);
app.v.Vacid(idx) = app.p.VT10 - app.v.VT1(previdx);

Din = DR1 + DR2 + DT1 + DT2;  % Total dilution rate [1/h]
TL  = app.v.thetaL(previdx) + app.p.TnG;  % Liquid temperature [K]

% Reactor pressure [N/m^2]
if app.v.thetaL(previdx) < 100
    app.v.pG(idx) = app.a.pGw;
else
    ExppDL        = 10.9 - 2461/TL - 2.065*log10(app.v.thetaL(previdx)/app.p.TnG);
    app.v.pG(idx) = 9.8067 * 10^ExppDL;
end

app.a.deltapG = (app.v.pG(previdx) - app.p.pnG) / 10^5;

% Respiration quotient [-]
RQ_Z = app.v.xCO2(previdx)/100 * (1 - app.v.xOGin(previdx)) - ...
       app.a.xCGin * (1 - app.v.xO2(previdx)/100);
RQ_N = app.v.xOGin(previdx) * (1 - app.v.xCO2(previdx)/100) - ...
       app.v.xO2(previdx)/100 * (1 - app.a.xCGin);
if RQ_N ~= 0
    app.v.RQ(idx) = RQ_Z / RQ_N;
else
    app.v.RQ(idx) = 1;
end
if app.v.RQ(previdx) <= 0
    app.v.RQ(previdx) = 0.0001;
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% pH iteration

y1 = (app.v.CB1Ltot(previdx) + 2*app.v.CB2Ltot(previdx)) / app.p.CH0;
y2 = (app.v.CB1Ltot(previdx) +   app.v.CB2Ltot(previdx)) / app.p.CH0;
y3 =  app.v.CCLtot(previdx)  / app.p.CH0;
y4 =  app.v.cP1L(previdx)    / app.p.CH0;
y5 =  app.v.CAlLtot(previdx) / app.p.CH0;
y6 =  app.v.CAcLtot(previdx) / app.p.CH0;

xpH    = 10^(7 - app.v.pH(previdx));
QuotpH = 0.9;

for i = 1:100
    if (QuotpH <= 0.999 || QuotpH >= 1.001) && xpH >= 0
        app.a.xpHkm1 = xpH;
        fpH0    = xpH^2 - 1;
        fpH1    = xpH * y1;
        fpH2    = -(app.a.ApH*xpH^2 + 2*app.a.BpH*xpH + 3*app.a.CpH) * xpH / ...
                  (xpH^3 + app.a.ApH*xpH^2 + app.a.BpH*xpH + app.a.CpH) * y2;
        fpH3    = -(app.a.DpH + 2*app.a.EpH/xpH) * y3;
        fpH4    = -app.a.FpH * xpH / (app.a.FpH + xpH) * y4;
        fpH5    =  app.a.GpH * xpH^2 / (1 + app.a.GpH*xpH) * y5;
        fpH6    = -(app.a.HpH*xpH + 2*app.a.IpH) * xpH / ...
                  (xpH^2 + app.a.HpH*xpH + app.a.IpH) * y6;
        fpH     = fpH0 + fpH1 + fpH2 + fpH3 + fpH4 + fpH5 + fpH6;

        fstrpH0 = 2*xpH;
        fstrpH1 = y1;
        fstrpH2 = -((app.a.ApH^2 - 2*app.a.BpH)*xpH^4 + ...
                   (2*app.a.ApH*app.a.BpH - 6*app.a.CpH)*xpH^3 + ...
                   2*app.a.BpH^2*xpH^2 + 4*app.a.BpH*app.a.CpH*xpH + ...
                   3*app.a.CpH^2) / ...
                  (xpH^3 + app.a.ApH*xpH^2 + app.a.BpH*xpH + app.a.CpH)^2 * y2;
        fstrpH3 =  2*app.a.EpH / (xpH*xpH) * y3;
        fstrpH4 = -app.a.FpH^2 / (xpH + app.a.FpH)^2 * y4;
        fstrpH5 =  app.a.GpH*xpH * (2 + app.a.GpH*xpH) / ...
                  (1 + app.a.GpH*xpH)^2 * y5;
        fstrpH6 = -((app.a.HpH^2 - 2*app.a.IpH)*xpH^2 + ...
                   2*app.a.HpH*app.a.IpH*xpH + 2*app.a.IpH^2) / ...
                  (xpH^2 + app.a.HpH*xpH + app.a.IpH)^2 * y6;
        fstrpH  = fstrpH0 + fstrpH1 + fstrpH2 + fstrpH3 + ...
                  fstrpH4 + fstrpH5 + fstrpH6;

        xpH    = xpH - fpH / fstrpH;
        QuotpH = app.a.xpHkm1 / xpH;
    else
        break
    end
end
if xpH < 0; xpH = -xpH; end

app.v.pHL(idx) = 7 - log10(xpH);
CHL            = xpH * app.p.CH0;  % H+ molar concentration [mol/l]

% pH and temperature influence on growth
if app.v.pHL(previdx) >= app.p.pHLmingr && app.v.pHL(previdx) <= app.p.pHLmaxgr
    fpH = (app.v.pHL(previdx) - app.p.pHLmingr) * ...
          (app.v.pHL(previdx) - app.p.pHLmaxgr) / ...
          ((app.v.pHL(previdx) - app.p.pHLmingr) * ...
           (app.v.pHL(previdx) - app.p.pHLmaxgr) - ...
           (app.v.pHL(previdx) - app.p.pHLoptgr)^2);
else
    fpH = 0;
end
if app.v.thetaL(previdx) >= app.p.thetaLmingr && ...
        app.v.thetaL(previdx) <= app.p.thetaLmaxgr
    ftheta = ((app.v.thetaL(previdx) - app.p.thetaLmaxgr) * ...
              (app.v.thetaL(previdx) - app.p.thetaLmingr)^2) / ...
             ((app.p.thetaLoptgr - app.p.thetaLmingr) * ...
              ((app.p.thetaLoptgr - app.p.thetaLmingr) * ...
               (app.v.thetaL(previdx) - app.p.thetaLoptgr) - ...
               (app.p.thetaLoptgr - app.p.thetaLmaxgr) * ...
               (app.p.thetaLoptgr + app.p.thetaLmingr - 2*app.v.thetaL(previdx))));
else
    ftheta = 0;
end

% Maximum specific growth rates [1/h]
my1max = app.p.my1opt * fpH * ftheta;  % glycerol

% Maximum specific glycerol uptake rate [1/h]
app.a.qS1pXmax = (my1max + app.a.mySm) / app.p.yXpS1gr;

% Maximum specific methanol uptake rate via Cornelissen kinetics [1/h]
cS2Lopt        = sqrt(app.p.kS2 * app.p.kI22);
app.a.qS2pXmax = app.p.qS2pXsup * ...
    (cS2Lopt / (app.p.kS2 + cS2Lopt)) * ...
    (app.p.kI22 / (app.p.kI22 + cS2Lopt));

% Optimal methanol growth rate and temperature/pH correction
app.p.my2opt = app.p.yXpS2gr * app.a.qS2pXmax - app.a.mySm;
my2max       = app.p.my2opt * fpH * ftheta;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Respiration

app.a.qOpXmax     = (my1max + app.a.mySm) / app.p.yXpOgr + app.p.qOpXm;
app.v.OURm(idx)   = app.p.qOpXm * app.v.cXL(previdx);
app.v.OURmax(idx) = app.a.qOpXmax * app.v.cXL(previdx);

% O2 Henry constant [Nm/kg]
app.a.HO2 = app.p.HnO2 / (1 + app.p.K1HO2*app.v.thetaL(previdx) + ...
    app.p.K2HO2*app.v.thetaL(previdx)^2 + ...
    app.p.K3HO2*app.v.thetaL(previdx)^3 + ...
    app.p.K4HO2*app.v.thetaL(previdx)^4);
app.a.cOL100 = app.p.pGcal * app.p.xOGcal / app.a.HO2;
app.a.cOLmax = app.v.pG(previdx) / app.a.HO2;

if app.v.VL(previdx) > 0
    app.v.QO2max(idx) = app.v.FnG(previdx) * 60 * app.p.MO2 / ...
        (app.p.VnM * app.v.VL(previdx));
else
    app.v.QO2max(idx) = 0;
end
app.v.QCO2max(idx) = app.v.QO2max(previdx) * app.p.MCO2 / app.p.MO2;

% Viscosity [Ns/m^2]
eta = app.p.etaXL * (app.p.etaH2O/app.p.etaXL)^(app.v.cXL(previdx)/app.p.cXLeta);

% kLa [1/h]
VLwert         = (app.v.VL(previdx) / app.p.VLmin)^app.p.alpha;
NStwert        = (app.v.NSt(previdx) / app.p.NStmax)^(3*app.p.alpha);
FGwert         = (app.v.FnG(previdx) / app.p.FnGmax)^app.p.beta;
etawert        = (eta / app.p.etaH2O)^app.p.gamma;
app.v.kLa(idx) = app.p.kLamin + app.p.kLamax * FGwert * NStwert / VLwert * ...
    etawert * (1 - app.v.AAF(previdx));

app.v.OTRmax(idx) = app.v.kLa(previdx) * app.a.cOLmax;

if app.v.QO2max(previdx) > 0
    StO = app.v.OTRmax(previdx) / app.v.QO2max(previdx);
else
    StO = 10^20;
end

app.v.xOL(idx) = app.v.cOL(previdx) / app.a.cOLmax;

denom_OTR = (1 + StO - (1 - app.v.RQ(previdx)) * StO * app.v.xOL(previdx));
app.v.OTR(idx) = app.v.OTRmax(previdx) * ...
    (app.v.xOGin(previdx) - app.v.xOL(previdx)) * 2 / ...
    (denom_OTR + sqrt(denom_OTR^2 - 4*(1 - app.v.RQ(previdx)) * StO * ...
    (app.v.xOGin(previdx) - app.v.xOL(previdx))));
if app.v.OTR(previdx) < 0
    app.v.OTR(previdx) = 0;
end

if app.v.OTR(previdx) ~= 0
    app.v.xOG(idx) = (app.v.QO2max(previdx) * app.v.xOGin(previdx) - ...
        app.v.OTR(previdx)) / (app.v.QO2max(previdx) - ...
        (1 - app.v.RQ(previdx)) * app.v.OTR(previdx));
else
    app.v.xOG(idx) = app.v.xOGin(previdx);
end

% CO2 Henry constant [Nm/kg]
app.a.HCO2 = app.p.HnCO2 / (1 + app.p.K1HCO2*app.v.thetaL(previdx) + ...
    app.p.K2HCO2*app.v.thetaL(previdx)^2 + ...
    app.p.K3HCO2*app.v.thetaL(previdx)^3 + ...
    app.p.K4HCO2*app.v.thetaL(previdx)^4);
app.a.cCLmax = app.v.pG(previdx) / app.a.HCO2;
app.a.cCL    = (CHL^2 * app.p.MCO2 * app.v.CCLtot(previdx)) / ...
               (CHL^2 + app.p.KC1*CHL + app.p.KC1*app.p.KC2);
app.a.xCL    = app.a.cCL / app.a.cCLmax;
app.a.CTRmax = app.p.deltaCpO * app.v.kLa(previdx) * app.a.cCLmax;

if app.v.QCO2max(previdx) > 0
    app.a.StC = app.a.CTRmax / app.v.QCO2max(previdx);
else
    app.a.StC = 10^20;
end

denom_CTR    = (1 + app.a.StC - (1 - 1/app.v.RQ(previdx)) * app.a.StC * app.a.xCL);
app.v.CTR(idx) = app.a.CTRmax * (app.a.xCGin - app.a.xCL) * 2 / ...
    (denom_CTR + sqrt(denom_CTR^2 - 4*(1 - 1/app.v.RQ(previdx)) * ...
    app.a.StC * (app.a.xCGin - app.a.xCL)));

app.v.xCG(idx) = (app.v.QCO2max(previdx) * app.a.xCGin - app.v.CTR(previdx)) / ...
    (app.v.QCO2max(previdx) - (1 - 1/app.v.RQ(previdx)) * app.v.CTR(previdx));

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Substrate uptake kinetics

% Glycerol uptake (S1) [1/h]
if app.v.cS1L(previdx) <= 0
    qS1pXopt = 0;
else
    qS1pXopt = app.a.qS1pXmax * app.v.cS1L(previdx) / ...
               (app.v.cS1L(previdx) + app.p.kS1);
end

% Methanol uptake (S2) — inhibited by glycerol [1/h]
if app.v.cS2L(previdx) <= 0
    qS2pXopt = 0;
else
    qS2pXopt = app.a.qS2pXmax * ...
        (app.v.cS2L(previdx) / (app.v.cS2L(previdx) + app.p.kS2)) * ...
        (app.p.kI22 / (app.p.kI22 + app.v.cS2L(previdx))) * ...
        (app.p.kI21 / (app.p.kI21 + app.v.cS1L(previdx)));
end

% Cell growth rates [1/h]
qXpXSgr = app.p.yXpS1gr * qS1pXopt + app.p.yXpS2gr * qS2pXopt;

if app.v.cOL(previdx) <= 0
    qXpXOgr = 0;
else
    qXpXOgr = app.p.yXpOgr * (app.a.qOpXmax - app.p.qOpXm) * ...
        app.v.cOL(previdx) / (app.p.kO + app.v.cOL(previdx));
end

if qXpXSgr < qXpXOgr
    qXpXgr = qXpXSgr;
else
    qXpXgr = qXpXOgr;
end

% Methanol toxicity effect
VS2tox = (app.v.cS2L(previdx)/app.p.kS2tox)^app.p.kappatox / ...
         (1 + (app.v.cS2L(previdx)/app.p.kS2tox)^app.p.kappatox);

if any(app.p.f_Inoc == 1)
    app.v.qXpX(idx) = qXpXgr - app.a.mySm - VS2tox * app.p.qXpXtox;
else
    app.v.qXpX(idx) = 0;
end

% Actual glycerol uptake [1/h]
SSG   = qXpXgr / app.p.yXpS1gr;
qS1pX = min(SSG, qS1pXopt);

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% AOX Induction (Cornelissen) — methanol metabolism

bS2script = app.p.aS2script + my2max;
bS2trans  = app.p.aS2trans  + my2max;
bS2act    = app.p.aS2act    + my2max;

% Switch-on / switch-off functions
VS2ind = (app.v.cS2L(previdx)/app.p.kS2ind)^app.p.kappaind / ...
         (1 + (app.v.cS2L(previdx)/app.p.kS2ind)^app.p.kappaind);
VS1rep = 1 / (1 + (app.v.cS1L(previdx)/app.p.kS1rep)^app.p.kapparep);

app.v.qS2pXind(idx) = VS1rep * VS2ind * app.p.qS2pXsup;

ODE_Induction = @(t,y) Pichia_Induction_Cornelissen( ...
    app.v.qXpX(previdx), app.v.qS2pXind(previdx), ...
    app.p.aS2script, app.p.aS2trans, app.p.aS2act, ...
    bS2script, bS2trans, bS2act, t, y);
[~,yInd] = ode15s(ODE_Induction, [0 app.a.deltat], [ ...
    app.v.qS2pXscript(previdx), ...
    app.v.qS2pXtrans(previdx), ...
    app.v.qS2pXact(previdx)]);

app.v.qS2pXscript(idx) = yInd(end,1);
app.v.qS2pXtrans(idx)  = yInd(end,2);
app.v.qS2pXact(idx)    = yInd(end,3);

% Actual methanol uptake rate [1/h]
app.v.qS2pX(idx) = app.v.qS2pXact(previdx) * ...
    (app.v.cS2L(previdx) / (app.p.kS2 + app.v.cS2L(previdx))) * ...
    (app.p.kI22 / (app.p.kI22 + app.v.cS2L(previdx))) * ...
    (app.p.kI21 / (app.p.kI21 + app.v.cS1L(previdx)));
qS2pX = app.v.qS2pX(idx);

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Product Expression (Cornelissen)

bP1script = app.p.aP1script + my2max;
bP1trans  = app.p.aP1trans  + my2max;
bP1act    = app.p.kP1alpha  + my2max;

app.v.qP1pXind(idx) = VS1rep * VS2ind * app.p.qP1pXsup;

% PI-based feedback controller for transcription setpoint
app.v.qP1pXscriptw(idx) = VS1rep * VS2ind * app.p.qP1pXmax;
delta_qP1pXscript        = app.v.qP1pXscriptw(previdx) - app.v.qP1pXscript(previdx);

% Accumulate integral via trapezoidal sum over full history
if app.nxtidx > 1
    tHist     = app.v.t(1:previdx);
    deltaHist = app.v.qP1pXscriptw(1:previdx) - app.v.qP1pXscript(1:previdx);
    intVal    = trapz(tHist, deltaHist);
    app.v.qP1pXback(idx) = app.p.KCP1script * ...
        (delta_qP1pXscript + intVal / app.p.TIP1script);
else
    app.v.qP1pXback(idx) = 0;
end

ODE_Expression = @(t,y) Pichia_Expression_Cornelissen( ...
    app.v.qXpX(previdx), app.v.qP1pXind(previdx), ...
    app.v.qP1pXback(previdx), app.p.aP1script, app.p.aP1trans, ...
    app.p.kP1alpha, bP1script, bP1trans, bP1act, t, y);
[~,yExp] = ode15s(ODE_Expression, [0 app.a.deltat], [ ...
    app.v.qP1pXscript(previdx), ...
    app.v.qP1pXtrans(previdx), ...
    app.v.qP1pXact(previdx)]);

app.v.qP1pXscript(idx) = yExp(end,1);
app.v.qP1pXtrans(idx)  = yExp(end,2);
app.v.qP1pXact(idx)    = yExp(end,3);
app.v.qP1pX(idx)       = app.v.qP1pXact(previdx);

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Remaining specific rates

qAlpX = app.p.yAlpXgr * qXpXgr;  % Ammonia uptake [1/h]
qAcpX = app.p.yAcpXgr * qXpXgr;  % Acid uptake [1/h]
qOpX  = qXpXgr / app.p.yXpOgr + app.p.qOpXm;  % O2 uptake [1/h]

if any(app.p.f_Inoc == 1)
    app.v.OUR(idx) = qOpX * app.v.cXL(previdx);
else
    app.v.OUR(idx) = 0;
end

CER  = app.p.yCpO * app.v.OUR(previdx);  % Volumetric CO2 production [g/(l*h)]
AlTR = -app.p.KAlvol * app.v.FnG(previdx) * app.v.CAlLtot(previdx) * ...
       app.p.MAl / app.v.VL(previdx);  % Ammonia transfer rate [g/(l*h)]

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Temperature system

if app.p.Mode_temp == 1
    DH     = app.p.mdotH / app.a.mHmax;
end
tauHTh = app.a.mHmax * app.p.cH2O / (app.a.kHTh * app.p.AHTh);

if app.p.Mode_temp == 1
    phiHTh = DH * tauHTh;
    phiHT  = app.p.mdotH / app.p.mdotT;
end

if app.p.Mode_temp == 0
    if app.p.f_heating == 1
        app.a.thetaTh = app.v.thetaD(previdx) + app.a.RT * PH;
    else
        app.a.thetaTh = app.v.thetaL(previdx);
    end
end
if app.p.Mode_temp == 1
    app.a.thetaTh = ((1 + phiHTh) * app.a.CHmax * app.v.thetaD(previdx) + ...
        phiHT * (app.a.CHmax * app.p.thetaHin + app.a.Qny)) / ...
        (app.a.CHmax * (1 + phiHTh + phiHT));
end

DC     = app.p.mdotC / app.p.mC;
phiCTc = DC * app.a.tauCTc;
app.a.thetaTc = (phiCTc * app.p.thetaCin + ...
    (1 + phiCTc) * app.a.phiTcC * app.a.thetaTh) / ...
    ((1 + app.a.phiTcC) * (1 + phiCTc) - 1);
app.a.thetaC  = (phiCTc * app.p.thetaCin + app.a.thetaTc) / (1 + phiCTc);
app.a.thetaDJ = app.a.thetaTc;

CL    = app.p.rhoL * app.v.VL(previdx) * app.p.cH2O + app.p.mWL * app.p.cW;
tauLD = CL / (app.a.kDL * app.p.ADL);
tauLU = CL / (app.a.kLU * app.p.ALU);
tauL  = 1 / (1/tauLD + 1/tauLU);

QdotM  = app.p.KHM  * app.v.VL(previdx) * app.v.OUR(previdx);
QdotSt = app.p.KHSt * app.v.VL(previdx) * app.v.NSt(previdx)^3;

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Concentration balance ODE — 19 states
% y = [cXL, cS1L, cS2L, cP1X, cP1L, cOL, pO2,
%      CB1Ltot, CB2Ltot, CAcLtot, CAlLtot, CCLtot,
%      pH, xO2, xCO2, hF, AAF, thetaD, thetaL]

ODE_concbal = @(t,y) Pichia_ODE_Luttmann( ...
    app.v.qXpX(previdx), Din, ...
    app.p.cS1R1, qS1pX, ...
    app.p.cS2R1, qS2pX, ...
    app.p.cS1R2, app.p.cS2R2, ...
    app.p.cP1R1, app.p.cP1R2, ...
    app.v.qP1pX(previdx), app.p.kP1alpha, ...
    app.p.cOT1, app.p.cOT2, app.p.cOR1, app.p.cOR2, ...
    app.v.OTR(previdx), app.v.OUR(previdx), ...
    app.a.cOL100, app.p.TMpO2, ...
    DT1, app.p.CAcT1tot, qAcpX, app.p.MAc, ...
    DT2, app.p.CAlT2tot, qAlpX, AlTR, app.p.MAl, ...
    DR1, DR2, app.p.CCR1tot, app.p.CCT1tot, app.p.CCT2tot, ...
    app.v.CTR(previdx), CER, app.p.MCO2, ...
    app.v.pHL(previdx), app.p.TMpH, ...
    app.p.TMxO2, app.v.xOG(previdx), ...
    app.p.TMxCO2, app.v.xCG(previdx), ...
    lambdaF, app.p.qhpX, lambdaAF, AAFin, ...
    app.a.tauD, app.a.DD, app.a.thetaTc, ...
    app.a.tauDL, app.p.thetaU, app.a.tauDU, ...
    tauL, tauLD, tauLU, QdotM, QdotSt, CL, t, y);

[~,y] = ode15s(ODE_concbal, [0 app.a.deltat], [ ...
    app.v.cXL(previdx)    app.v.cS1L(previdx)    app.v.cS2L(previdx) ...
    app.v.cP1X(previdx)   app.v.cP1L(previdx)    app.v.cOL(previdx) ...
    app.v.pO2(previdx)    app.v.CB1Ltot(previdx)  app.v.CB2Ltot(previdx) ...
    app.v.CAcLtot(previdx) app.v.CAlLtot(previdx) app.v.CCLtot(previdx) ...
    app.v.pH(previdx)     app.v.xO2(previdx)      app.v.xCO2(previdx) ...
    app.v.hF(previdx)     app.v.AAF(previdx)      app.v.thetaD(previdx) ...
    app.v.thetaL(previdx)]);

% Clamp all states to non-negative values
for i = 1:19
    if y(end,i) < 0
        y(end,i) = 0;
    end
end

% Inoculation check
if app.p.f_Inoc == 1 && app.a.inoc_occ == 0
    app.v.cXL(idx)   = app.p.cXL0;
    app.a.ToI        = app.v.t(previdx);
    app.a.inoc_occ   = 1;
    logMessage(app, 'Process Event', 'Inoculation occurred');
else
    app.v.cXL(idx) = y(end,1);
end
app.v.cS1L(idx)    = y(end,2);
app.v.cS2L(idx)    = y(end,3);
app.v.cP1X(idx)    = y(end,4);
app.v.cP1L(idx)    = y(end,5);
app.v.cOL(idx)     = y(end,6);
app.v.pO2(idx)     = y(end,7);
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
    app.v.thetaL(previdx) = 100.0;
    logMessage(app, 'Process Event', 'Temperature >100°C reached');
end

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Volumetric substrate intake rates

app.v.QS1in(idx) = (app.v.FR1(previdx)*app.p.cS1R1 + ...
    app.v.FR2(previdx)*app.p.cS1R2) / app.v.VL(previdx);
app.v.QS2in(idx) = (app.v.FR1(previdx)*app.p.cS2R1 + ...
    app.v.FR2(previdx)*app.p.cS2R2) / app.v.VL(previdx);

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Measurement transfer functions

app.v.pHLm(idx)    = meas_transfer_function(app.v.pHL(previdx),    app.v.pHLm(previdx),    app.p.taupHL,    app.a.deltat);
app.v.pO2m(idx)    = meas_transfer_function(app.v.pO2(previdx),    app.v.pO2m(previdx),    app.p.taupO2,    app.a.deltat);
app.v.thetaLm(idx) = meas_transfer_function(app.v.thetaL(previdx), app.v.thetaLm(previdx), app.p.tauthetaL, app.a.deltat);
app.v.cS1Lm(idx)   = meas_transfer_function(app.v.cS1L(previdx),   app.v.cS1Lm(previdx),   app.p.taucS1L,   app.a.deltat);
app.v.cS2Lm(idx)   = meas_transfer_function(app.v.cS2L(previdx),   app.v.cS2Lm(previdx),   app.p.taucS2L,   app.a.deltat);

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% Time advance

app.v.t(idx) = app.v.t(previdx) + app.a.deltat;

% Volume limit check
if app.v.VL(previdx) >= app.p.VLmax
    app.a.VolumeFlag = 1;
end
if any(app.a.VolumeFlag == 1) && any(app.a.VLflag == 0)
    app.a.VLflag = 1;
    stop(app.Refresher);
    msg = sprintf('VLmax of %g l was reached', app.p.VLmax);
    errordlg(msg);
    logMessage(app, 'Process Event', msg);
end

app.nxtidx = idx;
app_new    = app;
end
