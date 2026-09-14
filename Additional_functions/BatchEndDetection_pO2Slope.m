function flag = BatchEndDetection_pO2Slope(v, deltat, t, idx)
% BatchEndDetection_pO2Slope
%
% Detects the end of a batch phase by monitoring a simultaneous
% sharp pO2 rise and agitation (NSt) drop — the classical
% substrate depletion signature.
%
% Detection logic:
%   1. Smooth pO2 and NSt with a median filter (noise rejection)
%   2. Compute normalized slope via robust linear regression
%      over a configurable window
%   3. Apply hysteresis: condition must hold for min_confirm
%      consecutive steps before flagging true
%
% Inputs:
%   v       - variable struct (fields: pO2, NSt)
%   deltat  - simulation time step [h]
%   t       - process time array [h]
%   idx     - current index in v arrays
%
% Output:
%   flag    - true if batch end detected, false otherwise
%
% Parameters (tunable):
%   window_min   - regression window length [min], default 3
%   min_confirm  - consecutive steps required before flagging, default 3
%   thresh_pO2   - normalised pO2 slope threshold [%/h / %], default 5
%   thresh_NSt   - normalised NSt slope threshold [1/h / rpm], default -5

% ── Persistent state for hysteresis counter ──────────────────────────
persistent confirm_count;
if isempty(confirm_count)
    confirm_count = 0;
end

flag = false;

% ── Tunable parameters ────────────────────────────────────────────────
window_min   = 3;    % regression window [min]
min_confirm  = 3;    % steps before flag is raised
thresh_pO2   = 5;    % normalised slope threshold for pO2  [%/min]
thresh_NSt   = -5;   % normalised slope threshold for NSt  [rpm/min]

% ── Window length in samples ──────────────────────────────────────────
% deltat is in hours → convert window to hours first
window_h   = window_min / 60;
n_window   = max(3, round(window_h / deltat));

% ── Minimum data requirement ──────────────────────────────────────────
if idx < n_window + 1
    confirm_count = 0;
    return;
end

% ── Extract window ────────────────────────────────────────────────────
i0   = idx - n_window;
i1   = idx;

pO2_raw = v.pO2(i0:i1);
NSt_raw = v.NSt(i0:i1);
t_win   = t(i0:i1);

% ── Guard: skip if any values are NaN or zero NSt (uninitialised) ─────
if any(isnan(pO2_raw)) || any(isnan(NSt_raw)) || all(NSt_raw == 0)
    confirm_count = 0;
    return;
end

% ── Median smoothing (kernel = 5 samples, handles spikes) ────────────
% Custom sliding median — no Signal Processing Toolbox required
k     = min(5, floor(n_window / 2) * 2 + 1);  % odd kernel, max 5
pO2_s = slidingMedian(double(pO2_raw), k);
NSt_s = slidingMedian(double(NSt_raw), k);

% ── Robust linear regression (Theil-Sen median slope) ────────────────
% More robust than polyfit against outliers in short windows
t_win_d = double(t_win);

slope_pO2 = theilSenSlope(t_win_d, pO2_s);  % [%/h]
slope_NSt = theilSenSlope(t_win_d, NSt_s);  % [rpm/h]

% Convert from per-hour to per-minute for threshold comparison
slope_pO2_min = slope_pO2 / 60;   % [%/min]
slope_NSt_min = slope_NSt / 60;   % [rpm/min]

% ── Condition check ───────────────────────────────────────────────────
pO2_rising  = slope_pO2_min >  thresh_pO2;
NSt_falling = slope_NSt_min <  thresh_NSt;

% ── Hysteresis: both conditions must hold simultaneously ──────────────
if pO2_rising && NSt_falling
    confirm_count = confirm_count + 1;
else
    confirm_count = 0;  % reset on any step where condition breaks
end

if confirm_count >= min_confirm
    flag = true;
    fprintf('[BatchEndDetection] Batch end detected at t = %.3f h | ', t_win_d(end));
    fprintf('dpO2/dt = %.2f %%/min | dNSt/dt = %.2f rpm/min\n', ...
        slope_pO2_min, slope_NSt_min);
end

end


% ── Helper: Theil-Sen median slope estimator ─────────────────────────
% Computes the median of all pairwise slopes — robust to outliers.
% For short windows (n <= 30) this is fast enough.

function slope = theilSenSlope(x, y)
    n = numel(x);
    if n < 2
        slope = 0;
        return;
    end
    slopes = zeros(n*(n-1)/2, 1);
    k = 0;
    for i = 1:n-1
        for j = i+1:n
            dx = x(j) - x(i);
            if dx ~= 0
                k = k + 1;
                slopes(k) = (y(j) - y(i)) / dx;
            end
        end
    end
    if k == 0
        slope = 0;
    else
        slope = median(slopes(1:k));
    end
end


% ── Helper: sliding median filter (replaces medfilt1) ────────────────
% Uses edge-padding (repeat boundary values) — same as medfilt1 default.

function y = slidingMedian(x, k)
    n    = numel(x);
    half = floor(k / 2);
    % Pad signal at both ends by repeating boundary values
    xp   = [repmat(x(1), 1, half), x(:)', repmat(x(end), 1, half)];
    y    = zeros(1, n);
    for i = 1:n
        y(i) = median(xp(i:i+k-1));
    end
end