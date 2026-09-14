function centerWindow(UIFigure)
% Get the screen size
screenSize = get(0, 'ScreenSize');

% Get the app window size
appWidth = UIFigure.Position(3);
appHeight = UIFigure.Position(4);

% Calculate the new position
newX = (screenSize(3) - appWidth) / 2;
newY = (screenSize(4) - appHeight) / 2;

% Set the new position
UIFigure.Position = [newX, newY, appWidth, appHeight];
end