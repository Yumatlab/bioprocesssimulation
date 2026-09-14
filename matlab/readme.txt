Information for installation:

Note: Please download the most recent version. New versions can be downloaded from dropbox: 
https://www.dropbox.com/scl/fo/gk24excsno3cdnc128guf/ANHaf0CF_DjL0nQVCeV2098?rlkey=vi3nl48lkmc4fyh0rctwej8a8&st=7emuce8m&dl=0

Current version: Version 2.0

===========================================================================================
The biofermentation simulation software can either be run over MATLAB or as a compiled app. 
Note: The masters thesis was handed in without a compiled app, since existing bugs may lead to program crashes.
 
%%% MATLAB %%%%
To run the application over MATLAB, select the file "StartingScreen.mlapp". This will open the main menu of the simulation where a project can be initiated.

%%% Compiled App %%% 
Simply start the exe file and follow the instructions. If something goes wrong, please adress yuma.iff@gmx.net.

The application will be downloaded into the program files folder, where normal users do not have rights for data changes. Changing data is necessary to write in the database.
Thats why the SQLite 3 database and all organism-specific files will be automatically transferred into an AppData (Win+R -> "%AppData%" -> MathWorks -> BioProcessSimulationApp) folder.

%%%%%%%%%%%%%%%%%%%%%%Introducing new organisms%%%%%%%%%%%%%%%%%%%%%%%%
1. Insert dataset into organismTab file
2. create folder with the same name as the entry for "function_file" in organismTab
3. create a .m-function file with the model described mathematically
4. create a .m-function file calles "organismname"+_Initialization, where all parameters are defined and calculated, that are not saved within the database in project_parameterTab.
5. additionally insert variable data for t = 0 h inside the intialization file. It is recommended to be guided by existing the structures.
6. insert the organism-specific folder in the AppData directory, alligned with the other organism files and the database
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
